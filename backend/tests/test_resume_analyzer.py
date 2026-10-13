from datetime import datetime, timezone
from uuid import UUID, uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import StudentPrincipal, get_current_student
from app.db import get_db
from app.extraction import PDFProcessingError, extract_pdf
from app.main import app
from app.models import Base, JobRole, Resume, ResumeExtraction, StudentProfile


def make_pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    y = 60
    for line in text.splitlines():
        page.insert_text((60, y), line)
        y += 18
    payload = document.tobytes()
    document.close()
    return payload


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path / "resumes"))
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    client_student_id, client_user_id = uuid4(), uuid4()
    with factory() as session:
        session.add(StudentProfile(student_id=client_student_id, user_id=client_user_id))
        session.add(StudentProfile(student_id=uuid4(), user_id=uuid4()))
        session.commit()

    def override_db():
        with factory() as session:
            yield session

    def override_student():
        return StudentPrincipal(user_id=client_user_id, student_id=client_student_id)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_student] = override_student
    with TestClient(app) as test_client:
        yield test_client, factory, client_student_id
    app.dependency_overrides.clear()
    engine.dispose()


RESUME_TEXT = """Avery Student
avery@example.com
EDUCATION
BSc Computer Science, 2025
SKILLS
Python, SQL, React, Git
PROJECTS
Campus portal built with React and Python
EXPERIENCE
Developed REST APIs with Python and SQL for services
CERTIFICATIONS
AWS Cloud Practitioner
"""


def upload(client: TestClient, name="resume.pdf", content_type="application/pdf", payload=None):
    return client.post("/api/v1/me/resumes", files={"file": (name, payload if payload is not None else make_pdf(RESUME_TEXT), content_type)})


def test_upload_extracts_structured_resume_and_persists(api):
    client, factory, student_id = api
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["extracted_resume"]["email"] == "avery@example.com"
    assert {"Python", "SQL", "React"} <= set(body["extracted_resume"]["skills"])
    assert body["extracted_resume"]["education"]
    assert body["extracted_resume"]["projects"]
    assert body["extracted_resume"]["experience"]
    assert body["extracted_resume"]["certifications"]
    with factory() as session:
        resume = session.get(Resume, UUID(body["resume_id"]))
        extraction = session.get(ResumeExtraction, UUID(body["resume_id"]))
        assert resume.student_id == student_id
        assert extraction.extracted_text.startswith("Avery Student")


def test_upload_rejects_wrong_type_and_oversized_files(api, monkeypatch):
    client, _, _ = api
    wrong_type = upload(client, "resume.txt", "text/plain", b"not pdf")
    assert wrong_type.status_code == 415
    assert wrong_type.json()["detail"]["code"] == "unsupported_file_type"

    malformed = upload(client, payload=b"%PDF-this-is-not-a-valid-pdf")
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_pdf"

    monkeypatch.setenv("MAX_RESUME_BYTES", "10")
    oversized = upload(client, payload=b"%PDF-" + b"x" * 20)
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "file_too_large"


def test_extraction_rejects_malformed_and_scanned_pdf():
    with pytest.raises(PDFProcessingError, match="not a valid PDF"):
        extract_pdf(b"not a pdf", max_pages=10)

    image_pdf = pymupdf.open()
    image_pdf.new_page()
    scanned_payload = image_pdf.tobytes()
    image_pdf.close()
    with pytest.raises(PDFProcessingError, match="No selectable text"):
        extract_pdf(scanned_payload, max_pages=10)


def test_authentication_fails_closed_when_host_validator_is_absent(monkeypatch):
    monkeypatch.delenv("STUDENT_TOKEN_VALIDATOR", raising=False)
    with TestClient(app) as client:
        no_token = client.get("/api/v1/me/resumes")
        assert no_token.status_code == 401
        bearer = client.get("/api/v1/me/resumes", headers={"Authorization": "Bearer unverified-token"})
        assert bearer.status_code == 503
        assert bearer.json()["detail"]["code"] == "auth_integration_not_configured"


def test_resume_ownership_hides_other_students_data(api):
    client, factory, _ = api
    other_student_id = uuid4()
    resume_id = uuid4()
    with factory() as session:
        session.add(Resume(
            resume_id=resume_id, student_id=other_student_id, resume_file_name="private.pdf",
            resume_storage_path="unused", mime_type="application/pdf", file_size_kb=1,
            version=1, is_default=False, uploaded_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        session.commit()
    response = client.get(f"/api/v1/me/resumes/{resume_id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resume_not_found"


def test_analysis_returns_transparent_heuristic_and_retrievable_results(api):
    client, _, _ = api
    resume_response = upload(client)
    resume_id = resume_response.json()["resume_id"]
    response = client.post(f"/api/v1/me/resumes/{resume_id}/analyses", json={
        "job_description": "We seek Python React SQL Docker engineers to build reliable software systems.",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["score_method"] == "section_and_keyword_heuristic_v1"
    assert body["ats_score"] == 100
    assert body["skill_match_percentage"] < 100
    assert "Docker" in body["missing_keywords"]
    assert isinstance(body["strengths"], list)
    assert isinstance(body["weaknesses"], list)
    assert isinstance(body["recommendations"], list)

    retrieved = client.get(f"/api/v1/me/resume-analyses/{body['analysis_id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["analysis_id"] == body["analysis_id"]


def test_analysis_accepts_existing_job_role_reference(api):
    client, factory, _ = api
    resume_id = upload(client).json()["resume_id"]
    role_id = uuid4()
    with factory() as session:
        session.add(JobRole(job_role_id=role_id, role_title="Python Engineer", category="Software", description="Build Python services with SQL and Docker."))
        session.commit()
    response = client.post(f"/api/v1/me/resumes/{resume_id}/analyses", json={"job_role_id": str(role_id)})
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert "Docker" in response.json()["missing_keywords"]


def test_question_and_interview_endpoints_report_unconfigured_provider(api):
    client, _, _ = api
    resume_response = upload(client)
    resume_id = resume_response.json()["resume_id"]
    question = client.post(f"/api/v1/me/resumes/{resume_id}/questions", json={"question": "Which programming skills are in my resume?"})
    assert question.status_code == 503
    assert question.json()["detail"]["code"] == "ai_provider_not_configured"

    analysis = client.post(f"/api/v1/me/resumes/{resume_id}/analyses", json={
        "job_description": "A Python engineer will design reliable software services and systems.",
    }).json()
    interview = client.post(f"/api/v1/me/resume-analyses/{analysis['analysis_id']}/interview-questions", json={})
    assert interview.status_code == 503
    assert interview.json()["detail"]["code"] == "ai_provider_not_configured"
