from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    resume_storage_dir: Path
    max_resume_bytes: int
    max_pdf_pages: int
    ai_base_url: str | None
    ai_api_key: str | None
    ai_model: str | None
    ai_timeout_seconds: float
    student_token_validator: str | None


def get_settings() -> Settings:
    """Read environment configuration at call time for easy deployment and testing."""
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://campusconnect:campusconnect@localhost:5432/campusconnect",
        ),
        resume_storage_dir=Path(os.getenv("RESUME_STORAGE_DIR", "backend/.storage/resumes")),
        max_resume_bytes=int(os.getenv("MAX_RESUME_BYTES", str(10 * 1024 * 1024))),
        max_pdf_pages=int(os.getenv("MAX_RESUME_PAGES", "50")),
        ai_base_url=os.getenv("AI_BASE_URL"),
        ai_api_key=os.getenv("AI_API_KEY"),
        ai_model=os.getenv("AI_MODEL"),
        ai_timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "30")),
        student_token_validator=os.getenv("STUDENT_TOKEN_VALIDATOR"),
    )
