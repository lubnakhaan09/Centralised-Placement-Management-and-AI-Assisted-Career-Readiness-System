# AI Resume Analyzer API

This FastAPI service adds the Resume Analyzer API to the existing CampusConnect repository. It reuses the existing PostgreSQL `student_profiles`, `resumes`, `resume_analysis`, and `job_roles` tables. It does not implement login/refresh-token endpoints or Placement Match endpoints.

## Requirements and setup

Python 3.11+ and PostgreSQL are required. From the repository root, create and activate a virtual environment, then install the small backend dependency set:

```powershell
py -3.11 -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1
python -m pip install -r backend/requirements.txt
```

The checked-in base SQL schema does not include tables for persisted extracted text/sections or detailed analysis metrics. After applying the base database schema, apply the separate migration:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/001_resume_analyzer_persistence.sql
```

Set `DATABASE_URL` and an external `RESUME_STORAGE_DIR` before starting. Resume files are stored as UUID-named PDFs under `backend/.storage/resumes` by default; deployments should use a durable, private volume and restrict access to it. File bytes are not stored in PostgreSQL.

## Authentication integration

The checked-in project has no access-token implementation, so the API fails closed. Requests require a bearer token and `STUDENT_TOKEN_VALIDATOR` pointing to a trusted Python adapter as `python.module:function_name`. The function receives the raw token and must validate it using CampusConnect's real token rules, then return the authenticated user's UUID (or an object/dict with `user_id`). It may raise `app.auth.TokenValidationError` for an invalid token. Do not point this setting at an untrusted module and do not add a development bypass. If the host application already has a FastAPI dependency, wire that dependency to `get_current_student` instead of creating another auth system.

Without the adapter, authenticated routes return `503 auth_integration_not_configured`. A configured adapter that rejects the token returns `401`; a valid user without a `student_profiles` record gets `403`.

## AI provider

Resume analysis scores use the local, transparent heuristic described below. Resume Q&A and interview-question generation require an OpenAI-compatible chat-completions provider. Configure all three values; otherwise those endpoints return `503 ai_provider_not_configured` and do not produce fallback answers:

```powershell
$env:AI_BASE_URL = "https://provider.example/v1"
$env:AI_API_KEY = "your-secret"
$env:AI_MODEL = "provider-model-name"
```

The service sends the resume's extracted text to this provider for those two operations. Configure provider privacy/retention settings appropriately. Provider output is checked for the expected JSON shape but is not independently verified for factual accuracy.

## Run and test

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
uvicorn app.main:app --app-dir backend --reload
```

The app listens at `http://127.0.0.1:8000`; OpenAPI documentation is at `/docs`. Run focused tests from the repository root:

```powershell
python -m pytest backend/tests -q
```

The tests use an in-memory SQLite database and dependency overrides; they do not require PostgreSQL or a real token/AI provider.

## API overview

All student routes are under `/api/v1/me` and scope data to the authenticated student's existing profile.

- `POST /resumes` — multipart PDF upload and synchronous extraction; returns resume metadata and structured fields.
- `GET /resumes` and `GET /resumes/{resume_id}` — list or retrieve owned resume data without returning full extracted text.
- `POST /resumes/{resume_id}/analyses` — analyze against exactly one `job_role_id` or `job_description`.
- `GET /resume-analyses/{analysis_id}` — retrieve stored result metrics.
- `POST /resumes/{resume_id}/questions` — ask a question grounded in the extracted resume.
- `POST /resume-analyses/{analysis_id}/interview-questions` — generate technical, behavioral, project, and role-specific questions.

The upload limit defaults to 10 MiB (`MAX_RESUME_BYTES`); the PDF page limit defaults to 50 (`MAX_RESUME_PAGES`). The service checks filename/media type, PDF signature, page count, encryption, and parseability. PyMuPDF text extraction does not perform OCR; scanned image PDFs return `422 no_extractable_text`.

ATS score is a section-completeness heuristic (contact, skills, education, experience, projects; 20 points each). Keyword score is resume-token recall against meaningful tokens from the supplied job description or role text. Skill match compares recognized skills; experience match measures target-token overlap with the detected experience section. Overall job match is 40% skill, 35% keyword, and 25% experience. Formatting score is only a text-section structure heuristic; it does not inspect visual page layout or claim prediction of any commercial ATS. These heuristics have not been evaluated against hiring outcomes.

## Persistence and profile safety

The existing `resumes` row stores file metadata/path; `resume_extractions` stores extracted text and structured sections; the existing `resume_analysis` row stores ATS/match score and JSON-encoded result lists in its text fields; `resume_analysis_details` stores the job-description snapshot and breakdown scores. The service reads the student's resume and existing role only. It does not write extracted details into canonical `student_skills`, `projects`, or `certifications` tables.
