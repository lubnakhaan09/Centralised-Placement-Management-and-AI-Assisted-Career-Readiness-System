from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import ai
from ..analyzer import analyze_resume
from ..auth import StudentPrincipal, get_current_student
from ..config import get_settings
from ..db import get_db
from ..extraction import PDFProcessingError, extract_pdf
from ..models import JobRole, Resume, ResumeAnalysis, ResumeAnalysisDetail, ResumeExtraction
from ..schemas import (
    AnalysisRequest,
    AnalysisResponse,
    InterviewQuestionsRequest,
    InterviewQuestionsResponse,
    QuestionRequest,
    QuestionResponse,
    ResumeResponse,
    StructuredResume,
)
from ..storage import delete_pdf, safe_pdf_name, save_pdf

router = APIRouter(prefix="/api/v1/me", tags=["resume-analyzer"])
MAX_CHUNK_BYTES = 1024 * 1024


def _utcnow_naive() -> datetime:
    # The checked-in PostgreSQL schema uses timestamp without time zone.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _api_error(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _owned_resume(db: Session, resume_id: UUID, student_id: UUID) -> Resume:
    try:
        resume = db.scalar(select(Resume).where(Resume.resume_id == resume_id, Resume.student_id == student_id))
    except SQLAlchemyError:
        _api_error(503, "database_unavailable", "Resume data could not be loaded.")
    if resume is None:
        _api_error(404, "resume_not_found", "The requested resume was not found.")
    return resume


def _owned_extraction(db: Session, resume_id: UUID) -> ResumeExtraction:
    try:
        extraction = db.get(ResumeExtraction, resume_id)
    except SQLAlchemyError:
        _api_error(503, "database_unavailable", "Resume extraction data could not be loaded.")
    if extraction is None:
        _api_error(409, "extraction_unavailable", "This resume has no saved text extraction. Upload it again to process it.")
    return extraction


def _resume_response(resume: Resume, extraction: ResumeExtraction) -> ResumeResponse:
    return ResumeResponse(
        resume_id=resume.resume_id,
        file_name=resume.resume_file_name,
        mime_type=resume.mime_type,
        file_size_kb=resume.file_size_kb or 0,
        version=resume.version,
        is_default=bool(resume.is_default),
        uploaded_at=resume.uploaded_at,
        extracted_resume=StructuredResume.model_validate(extraction.structured_data),
    )


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        result = json.loads(value)
        if isinstance(result, list):
            return [str(item) for item in result]
    except (json.JSONDecodeError, TypeError):
        pass
    return [value]


def _analysis_response(analysis: ResumeAnalysis, detail: ResumeAnalysisDetail | None) -> AnalysisResponse:
    return AnalysisResponse(
        analysis_id=analysis.analysis_id,
        resume_id=analysis.resume_id,
        score_method=detail.scoring_method if detail else "legacy_unavailable",
        ats_score=float(analysis.ats_score or 0),
        keyword_match_percentage=float(detail.keyword_match_percentage or 0) if detail else 0,
        skill_match_percentage=float(detail.skill_match_percentage or 0) if detail else 0,
        experience_match_percentage=float(detail.experience_match_percentage or 0) if detail else 0,
        formatting_score=float(detail.formatting_score or 0) if detail else 0,
        job_match_percentage=float(analysis.job_match_percentage or 0),
        strengths=_json_list(analysis.strengths),
        weaknesses=_json_list(analysis.weaknesses),
        missing_keywords=_json_list(analysis.missing_keywords),
        recommendations=_json_list(analysis.recommendations),
        analyzed_at=analysis.analyzed_at or _utcnow_naive(),
    )


@router.post("/resumes", response_model=ResumeResponse, status_code=201)
def upload_resume(
    file: UploadFile = File(...),
    is_default: bool | None = Form(default=None),
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    submitted_name = (file.filename or "").replace("\\", "/").split("/")[-1]
    filename = safe_pdf_name(file.filename)
    if not submitted_name.lower().endswith(".pdf") or file.content_type not in {"application/pdf", "application/octet-stream"}:
        _api_error(415, "unsupported_file_type", "Upload a PDF file with a .pdf filename.")

    chunks, total = [], 0
    while True:
        try:
            chunk = file.file.read(MAX_CHUNK_BYTES)
        except OSError:
            _api_error(400, "upload_read_failed", "The uploaded file could not be read.")
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_resume_bytes:
            _api_error(413, "file_too_large", f"The PDF exceeds the {settings.max_resume_bytes} byte upload limit.")
        chunks.append(chunk)
    if total == 0:
        _api_error(422, "empty_file", "The uploaded PDF is empty.")
    payload = b"".join(chunks)
    try:
        text, structured = extract_pdf(payload, settings.max_pdf_pages)
    except PDFProcessingError as exc:
        _api_error(exc.status_code, exc.code, exc.message)

    resume_id = uuid4()
    storage_path: Path | None = None
    try:
        current_version = db.scalar(select(func.max(Resume.version)).where(Resume.student_id == student.student_id)) or 0
        first_resume = current_version == 0
        make_default = bool(is_default) if is_default is not None else first_resume
        if make_default:
            db.execute(update(Resume).where(Resume.student_id == student.student_id).values(is_default=False))
        storage_path = save_pdf(resume_id, payload)
        resume = Resume(
            resume_id=resume_id,
            student_id=student.student_id,
            resume_file_name=filename,
            resume_storage_path=str(storage_path),
            mime_type="application/pdf",
            file_size_kb=max(1, math.ceil(total / 1024)),
            version=int(current_version) + 1,
            is_default=make_default,
            uploaded_at=_utcnow_naive(),
        )
        extraction = ResumeExtraction(
            resume_id=resume_id,
            extracted_text=text,
            structured_data=structured,
            extraction_version="pymupdf-heuristic-v1",
            created_at=_utcnow_naive(),
        )
        db.add_all([resume, extraction])
        db.commit()
        return _resume_response(resume, extraction)
    except HTTPException:
        db.rollback()
        if storage_path:
            delete_pdf(str(storage_path))
        raise
    except (OSError, SQLAlchemyError):
        db.rollback()
        if storage_path:
            delete_pdf(str(storage_path))
        _api_error(503, "resume_persistence_failed", "The resume could not be saved. Please try again.")
    finally:
        file.file.close()


@router.get("/resumes/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: UUID,
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    resume = _owned_resume(db, resume_id, student.student_id)
    return _resume_response(resume, _owned_extraction(db, resume_id))


@router.get("/resumes", response_model=list[ResumeResponse])
def list_resumes(
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    try:
        resumes = db.scalars(select(Resume).where(Resume.student_id == student.student_id).order_by(Resume.uploaded_at.desc())).all()
        extractions = {item.resume_id: item for item in db.scalars(select(ResumeExtraction).where(ResumeExtraction.resume_id.in_([r.resume_id for r in resumes]))).all()} if resumes else {}
    except SQLAlchemyError:
        _api_error(503, "database_unavailable", "Resume data could not be loaded.")
    return [_resume_response(resume, extractions[resume.resume_id]) for resume in resumes if resume.resume_id in extractions]


@router.post("/resumes/{resume_id}/analyses", response_model=AnalysisResponse, status_code=201)
def analyze_resume_endpoint(
    resume_id: UUID,
    request: AnalysisRequest,
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    resume = _owned_resume(db, resume_id, student.student_id)
    extraction = _owned_extraction(db, resume_id)
    job_role_id = request.job_role_id
    if job_role_id:
        try:
            role = db.get(JobRole, job_role_id)
        except SQLAlchemyError:
            _api_error(503, "database_unavailable", "Job-role data could not be loaded.")
        if role is None:
            _api_error(404, "job_role_not_found", "The requested job role was not found.")
        target_text = " ".join(value for value in [role.role_title, role.category, role.description] if value)
    else:
        target_text = request.job_description or ""

    scores = analyze_resume(extraction.extracted_text, extraction.structured_data, target_text)
    analysis_id, analyzed_at = uuid4(), _utcnow_naive()
    analysis = ResumeAnalysis(
        analysis_id=analysis_id,
        resume_id=resume.resume_id,
        job_role_id=job_role_id,
        ats_score=Decimal(str(scores["ats_score"])),
        job_match_percentage=Decimal(str(scores["job_match_percentage"])),
        missing_keywords=json.dumps(scores["missing_keywords"]),
        strengths=json.dumps(scores["strengths"]),
        weaknesses=json.dumps(scores["weaknesses"]),
        recommendations=json.dumps(scores["recommendations"]),
        analyzed_at=analyzed_at,
    )
    detail = ResumeAnalysisDetail(
        analysis_id=analysis_id,
        target_job_description=request.job_description,
        keyword_match_percentage=Decimal(str(scores["keyword_match_percentage"])),
        skill_match_percentage=Decimal(str(scores["skill_match_percentage"])),
        experience_match_percentage=Decimal(str(scores["experience_match_percentage"])),
        formatting_score=Decimal(str(scores["formatting_score"])),
        scoring_method=scores["scoring_method"],
    )
    try:
        db.add_all([analysis, detail])
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _api_error(503, "analysis_persistence_failed", "The analysis could not be saved.")
    return _analysis_response(analysis, detail)


@router.get("/resume-analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: UUID,
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    try:
        row = db.execute(
            select(ResumeAnalysis, ResumeAnalysisDetail)
            .join(Resume, Resume.resume_id == ResumeAnalysis.resume_id)
            .outerjoin(ResumeAnalysisDetail, ResumeAnalysisDetail.analysis_id == ResumeAnalysis.analysis_id)
            .where(ResumeAnalysis.analysis_id == analysis_id, Resume.student_id == student.student_id)
        ).first()
    except SQLAlchemyError:
        _api_error(503, "database_unavailable", "Analysis data could not be loaded.")
    if row is None:
        _api_error(404, "analysis_not_found", "The requested analysis was not found.")
    return _analysis_response(row[0], row[1])


@router.post("/resumes/{resume_id}/questions", response_model=QuestionResponse)
def resume_question(
    resume_id: UUID,
    request: QuestionRequest,
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    _owned_resume(db, resume_id, student.student_id)
    extraction = _owned_extraction(db, resume_id)
    try:
        result = ai.answer_resume_question(extraction.extracted_text, request.question, request.job_description)
    except ai.AIProviderError as exc:
        _api_error(exc.status_code, exc.code, exc.message)
    return QuestionResponse(resume_id=resume_id, **result)


@router.post("/resume-analyses/{analysis_id}/interview-questions", response_model=InterviewQuestionsResponse)
def interview_questions(
    analysis_id: UUID,
    request: InterviewQuestionsRequest,
    student: StudentPrincipal = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    try:
        row = db.execute(
            select(ResumeAnalysis, Resume, ResumeExtraction, ResumeAnalysisDetail, JobRole)
            .join(Resume, Resume.resume_id == ResumeAnalysis.resume_id)
            .join(ResumeExtraction, ResumeExtraction.resume_id == Resume.resume_id)
            .outerjoin(ResumeAnalysisDetail, ResumeAnalysisDetail.analysis_id == ResumeAnalysis.analysis_id)
            .outerjoin(JobRole, JobRole.job_role_id == ResumeAnalysis.job_role_id)
            .where(ResumeAnalysis.analysis_id == analysis_id, Resume.student_id == student.student_id)
        ).first()
    except SQLAlchemyError:
        _api_error(503, "database_unavailable", "Analysis data could not be loaded.")
    if row is None:
        _api_error(404, "analysis_not_found", "The requested analysis was not found.")
    analysis, resume, extraction, detail, role = row
    try:
        questions = ai.generate_interview_questions(
            extraction.extracted_text,
            request.categories,
            request.count_per_category,
            request.difficulty,
            request.job_description or (detail.target_job_description if detail else None) or (" ".join(value for value in [role.role_title, role.category, role.description] if value) if role else None),
        )
    except ai.AIProviderError as exc:
        _api_error(exc.status_code, exc.code, exc.message)
    return InterviewQuestionsResponse(analysis_id=analysis.analysis_id, questions=questions)
