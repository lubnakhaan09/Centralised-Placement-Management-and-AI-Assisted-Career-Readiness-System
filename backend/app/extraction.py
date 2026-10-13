"""PDF validation and deliberately heuristic text/section extraction."""
import re

import pymupdf


class PDFProcessingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


SECTION_NAMES = {
    "skills": {"skills", "technical skills", "core competencies", "technologies"},
    "education": {"education", "academic background", "academics"},
    "projects": {"projects", "personal projects", "academic projects"},
    "experience": {"experience", "work experience", "professional experience", "employment", "internships"},
    "certifications": {"certifications", "certificates", "licenses and certifications"},
}
KNOWN_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "SQL", "PostgreSQL", "MySQL", "React", "Node.js",
    "FastAPI", "Django", "Flask", "HTML", "CSS", "REST API", "Docker", "Kubernetes", "AWS", "Azure", "GCP",
    "Git", "Linux", "Machine Learning", "TensorFlow", "PyTorch", "Pandas", "NumPy", "Excel", "Power BI", "Figma",
]


def _section_for(line: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    for section, names in SECTION_NAMES.items():
        if normalized in names:
            return section
    return None


def parse_resume_text(text: str) -> dict:
    lines = [re.sub(r"\s+", " ", line).strip(" •\t-*") for line in text.splitlines()]
    lines = [line for line in lines if line]
    sections: dict[str, list[str]] = {name: [] for name in SECTION_NAMES}
    current = None
    for line in lines:
        heading = _section_for(line)
        if heading:
            current = heading
            continue
        if current:
            sections[current].append(line)

    skills_text = "\n".join(sections["skills"])
    skills = [skill for skill in KNOWN_SKILLS if re.search(rf"(?<![\w+#]){re.escape(skill)}(?![\w+#])", skills_text, re.IGNORECASE)]
    # Also retain known skills when they occur in the resume outside a labeled skills section.
    all_text = "\n".join(lines)
    for skill in KNOWN_SKILLS:
        if skill not in skills and re.search(rf"(?<![\w+#]){re.escape(skill)}(?![\w+#])", all_text, re.IGNORECASE):
            skills.append(skill)

    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE)
    phone_match = re.search(r"(?:\+?\d[\d ()-]{7,}\d)", text)
    full_name = next((line for line in lines[:6] if "@" not in line and not re.search(r"https?://|www\.|\d{6,}", line, re.I) and len(line) <= 100), None)
    return {
        "full_name": full_name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "skills": skills,
        "education": sections["education"],
        "projects": sections["projects"],
        "experience": sections["experience"],
        "certifications": sections["certifications"],
    }


def extract_pdf(payload: bytes, max_pages: int) -> tuple[str, dict]:
    if not payload or b"%PDF-" not in payload[:1024]:
        raise PDFProcessingError("invalid_pdf", "The uploaded file is not a valid PDF.")
    try:
        document = pymupdf.open(stream=payload, filetype="pdf")
        try:
            if document.needs_pass:
                raise PDFProcessingError("encrypted_pdf", "Password-protected PDFs are not supported.")
            if document.page_count > max_pages:
                raise PDFProcessingError("too_many_pages", f"The PDF exceeds the {max_pages}-page limit.", 413)
            text_parts = [page.get_text("text") for page in document]
        finally:
            document.close()
    except PDFProcessingError:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise PDFProcessingError("invalid_pdf", "The PDF is damaged or could not be opened.") from exc

    text = "\n".join(text_parts).strip()
    if not text:
        raise PDFProcessingError("no_extractable_text", "No selectable text was found. Scanned PDFs require OCR and are not supported by this MVP.")
    if len(text) > 1_000_000:
        text = text[:1_000_000]
    return text, parse_resume_text(text)
