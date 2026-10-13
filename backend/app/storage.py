from pathlib import Path
import re
from uuid import UUID

from .config import get_settings


def safe_pdf_name(filename: str | None) -> str:
    original = (filename or "resume.pdf").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", original).strip(" .")
    return cleaned[:255] if cleaned.lower().endswith(".pdf") else (cleaned[:250] + ".pdf")


def save_pdf(resume_id: UUID, payload: bytes) -> Path:
    root = get_settings().resume_storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{resume_id}.pdf"
    temporary = root / f".{resume_id}.upload"
    try:
        temporary.write_bytes(payload)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def delete_pdf(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        # A failed cleanup must not hide the database error that caused it.
        pass
