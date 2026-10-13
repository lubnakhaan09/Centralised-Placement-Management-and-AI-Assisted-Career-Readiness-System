from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StructuredResume(APIModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class ResumeResponse(APIModel):
    resume_id: UUID
    file_name: str
    mime_type: str
    file_size_kb: int
    version: int
    is_default: bool
    uploaded_at: datetime
    status: str = "ready"
    extracted_resume: StructuredResume


class AnalysisRequest(APIModel):
    job_role_id: UUID | None = None
    job_description: str | None = Field(default=None, min_length=30, max_length=20_000)

    @model_validator(mode="after")
    def one_target(self):
        if (self.job_role_id is None) == (self.job_description is None):
            raise ValueError("Provide exactly one of job_role_id or job_description.")
        return self


class AnalysisResponse(APIModel):
    analysis_id: UUID
    resume_id: UUID
    status: str = "completed"
    score_method: str
    ats_score: float
    keyword_match_percentage: float
    skill_match_percentage: float
    experience_match_percentage: float
    formatting_score: float
    job_match_percentage: float
    strengths: list[str]
    weaknesses: list[str]
    missing_keywords: list[str]
    recommendations: list[str]
    analyzed_at: datetime


class QuestionRequest(APIModel):
    question: str = Field(min_length=3, max_length=2_000)
    job_description: str | None = Field(default=None, max_length=20_000)


class QuestionResponse(APIModel):
    resume_id: UUID
    answer: str
    evidence: list[str]


class InterviewQuestionsRequest(APIModel):
    categories: list[str] = Field(default_factory=lambda: ["technical", "behavioral", "project", "role_specific"], min_length=1)
    count_per_category: int = Field(default=3, ge=1, le=10)
    difficulty: str = Field(default="mixed", pattern="^(mixed|entry|intermediate|advanced)$")
    job_description: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def categories_allowed(self):
        allowed = {"technical", "behavioral", "project", "role_specific"}
        if not set(self.categories) <= allowed:
            raise ValueError("Categories must be technical, behavioral, project, or role_specific.")
        return self


class InterviewQuestion(APIModel):
    category: str
    question: str
    rationale: str | None = None


class InterviewQuestionsResponse(APIModel):
    analysis_id: UUID
    questions: list[InterviewQuestion]
