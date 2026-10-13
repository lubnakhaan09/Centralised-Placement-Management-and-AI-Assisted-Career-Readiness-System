from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class StudentProfile(Base):
    """The identity link needed from the existing student_profiles table."""
    __tablename__ = "student_profiles"

    student_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, nullable=False, index=True)


class JobRole(Base):
    __tablename__ = "job_roles"

    job_role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    role_title: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)


class Resume(Base):
    __tablename__ = "resumes"

    resume_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    student_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_profiles.student_id"), nullable=False, index=True)
    resume_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    resume_storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size_kb: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool | None] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResumeAnalysis(Base):
    __tablename__ = "resume_analysis"

    analysis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    resume_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("resumes.resume_id"), nullable=False, index=True)
    job_role_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("job_roles.job_role_id"))
    ats_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    job_match_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    missing_keywords: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ResumeExtraction(Base):
    __tablename__ = "resume_extractions"

    resume_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("resumes.resume_id", ondelete="CASCADE"), primary_key=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResumeAnalysisDetail(Base):
    __tablename__ = "resume_analysis_details"

    analysis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("resume_analysis.analysis_id", ondelete="CASCADE"), primary_key=True)
    target_job_description: Mapped[str | None] = mapped_column(Text)
    keyword_match_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    skill_match_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    experience_match_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    formatting_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    scoring_method: Mapped[str] = mapped_column(String(50), nullable=False)
