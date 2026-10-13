# AI Resume Analyzer Backend — Implementation Report

**Project:** CampusConnect (Centralised Placement Management and AI-Assisted Career Readiness System)  
**Scope:** Backend MVP implementation for AI Resume Analyzer only. Placement Match, frontend integration, and authentication-service implementation are out of scope.

## 1. Summary

Implemented a FastAPI backend under `backend/` for student-owned PDF resume upload, validation, text extraction, heuristic resume analysis, resume Q&A, and interview-question generation. The implementation reuses existing PostgreSQL entities (`student_profiles`, `resumes`, `resume_analysis`, and `job_roles`) and does not create a second student profile or authentication system. A migration adds only the persistence needed for extracted resume content and detailed analysis snapshots.

The API does not include a development authentication bypass. Authentication is a fail-closed adapter boundary because this repository did not establish an existing bearer-token format or validator. AI-generated features require a configured OpenAI-compatible provider; when it is absent, the API returns a configuration error rather than inventing answers.

## 2. Files created or changed

### Created

| File | Purpose |
|---|---|
| `backend/requirements.txt` | Minimal Python dependencies for the FastAPI service, PostgreSQL/SQLAlchemy, PDF extraction, HTTP provider calls, and tests. |
| `backend/README.md` | Backend setup, configuration, migration, endpoint, and test instructions. |
| `backend/app/__init__.py` | Python package marker. |
| `backend/app/main.py` | FastAPI application construction and router registration. |
| `backend/app/config.py` | Environment-backed service settings and defaults. |
| `backend/app/db.py` | SQLAlchemy engine/session setup and request-scoped database dependency. |
| `backend/app/models.py` | SQLAlchemy mappings for reused schema entities and added persistence entities. |
| `backend/app/schemas.py` | Pydantic request/response models and validation. |
| `backend/app/auth.py` | Fail-closed bearer-token dependency and configurable trusted validator adapter. |
| `backend/app/storage.py` | Private local resume-file storage and safe file naming. |
| `backend/app/extraction.py` | PDF validation, PyMuPDF text extraction, and heuristic structured extraction. |
| `backend/app/analyzer.py` | Transparent heuristic ATS and role-match analysis. |
| `backend/app/ai.py` | Configurable OpenAI-compatible provider integration for Q&A and interview questions. |
| `backend/app/routes/__init__.py` | Routes package marker. |
| `backend/app/routes/resumes.py` | Resume, analysis, Q&A, and interview-question endpoints, including ownership checks. |
| `backend/migrations/001_resume_analyzer_persistence.sql` | Separate SQL migration for extracted text/structured data and detailed analysis snapshots. |
| `backend/tests/conftest.py` | Focused test fixtures and dependency overrides. |
| `backend/tests/test_resume_analyzer.py` | Tests for upload validation, extraction failures, authentication/ownership, and analysis responses. |

### Changed

| File | Change |
|---|---|
| `.gitignore` | Ignores `backend/.storage/` so uploaded resume PDFs are not accidentally committed; also removes pre-existing stray merge-conflict marker lines encountered in the file. |

No frontend files were changed. No canonical student profile fields were written or overwritten. No login or refresh-token endpoints were added.

## 3. API overview

All routes are under `/api/v1`. Student-facing routes require a valid bearer token resolved through the configured trusted validator. Successful response examples below are representative; generated IDs and timestamps vary.

### Upload a resume

`POST /api/v1/me/resumes` — `multipart/form-data`, field `file`.

Uploads a PDF for the authenticated student, validates it, extracts text and structured sections, then persists resume metadata and extraction data.

Representative response (`201`):

```json
{
  "id": "<resume-uuid>",
  "filename": "resume.pdf",
  "content_type": "application/pdf",
  "size_bytes": 48231,
  "status": "processed",
  "extracted": {
    "skills": ["Python", "SQL"],
    "education": [],
    "projects": [],
    "experience": [],
    "certifications": []
  }
}
```

Validation includes filename/type, configured maximum size (default 10 MiB), PDF signature/readability, encryption, page count (maximum 50 by default), and extractable text. Scanned/image-only PDFs are not OCR-processed and return `422 no_extractable_text`.

### List and inspect resumes

- `GET /api/v1/me/resumes` — lists only the authenticated student’s resumes.
- `GET /api/v1/me/resumes/{resume_id}` — returns the owned resume and extracted structured information.

Unknown or non-owned resume IDs return `404`, avoiding disclosure of another student’s records.

### Analyze for a role or job description

`POST /api/v1/me/resumes/{resume_id}/analyses`

Supply exactly one target: `job_role_id`, or `job_description` (optionally with `target_role`). A role ID references the existing `job_roles` table. The response includes the ATS score and breakdown, strengths, weaknesses, missing keywords, recommendations, and match results.

Representative response (`201`):

```json
{
  "id": "<analysis-uuid>",
  "resume_id": "<resume-uuid>",
  "ats_score": 72,
  "scoring_method": "section_and_keyword_heuristic_v1",
  "score_breakdown": {
    "contact": 20,
    "skills": 15,
    "education": 20,
    "experience": 10,
    "projects": 7
  },
  "strengths": ["Contact information is present"],
  "weaknesses": ["Experience section has limited role-relevant evidence"],
  "missing_keywords": ["postgresql"],
  "recommendations": ["Add concrete examples that demonstrate PostgreSQL experience"],
  "matched_skills": ["Python"],
  "created_at": "<UTC timestamp>"
}
```

`GET /api/v1/me/resume-analyses/{analysis_id}` retrieves an owned analysis and its saved detail snapshot.

### Resume Q&A

`POST /api/v1/me/resumes/{resume_id}/questions`

Request: `{ "question": "Which projects demonstrate data analysis?" }`  
Response (`200`): `{ "answer": "<provider-generated answer grounded in the resume>", "provider": "<configured provider>" }`

Requires a configured AI provider. Missing configuration returns `503 ai_provider_not_configured`; provider failures are surfaced as service errors rather than replaced with fabricated content.

### Generate interview questions

`POST /api/v1/me/resume-analyses/{analysis_id}/interview-questions`

Request: `{ "count": 5 }`  
Response (`200`): `{ "questions": ["<generated question>"], "provider": "<configured provider>" }`

Questions are generated using the owned resume and associated analysis/target context. This also requires a configured AI provider.

### Error handling

The API uses clear HTTP errors for malformed requests, missing resources, and processing/configuration problems. Important cases include `400` for invalid target combinations, `401` for absent/invalid credentials, `404` for absent or non-owned resources, `413` for oversized uploads, `415` for unsupported file type, `422` for malformed/unreadable/encrypted or textless PDFs and field validation, `503` when auth integration or the AI provider is unconfigured, and service errors for database/provider failures. Error responses include a machine-readable code and a human-readable detail.

## 4. Data persistence and migration

The backend maps to existing student/profile, resume, role, and resume-analysis tables in `database/sql/placement_management_v1.sql`. Ownership is tied to the authenticated student identifier. The implementation does not update canonical student-profile data based on parsed resume content.

The separate migration `backend/migrations/001_resume_analyzer_persistence.sql` adds:

- `resume_extractions`: extracted text, structured JSON data, extraction version, resume reference, and timestamp.
- `resume_analysis_details`: target/job-description snapshot, score breakdown, and scoring-method metadata linked to a resume analysis.

Apply against the intended PostgreSQL database after reviewing the SQL:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/001_resume_analyzer_persistence.sql
```

The migration was created but was **not applied** to a PostgreSQL instance during this work. The app expects the repository schema and migration to be provisioned before database-backed operation.

## 5. Scoring, extraction, storage, and AI behavior

- **Scoring:** The ATS score is a transparent heuristic, not a measured or validated prediction. It evaluates resume section/contact presence and role-keyword evidence; the method is identified as `section_and_keyword_heuristic_v1`. It must not be represented as independently validated ATS accuracy.
- **Extraction:** PyMuPDF extracts text from readable PDFs. Section and skill identification are heuristic and can miss unusual layouts or wording. No OCR is included.
- **Storage:** Resume files are stored under a private local directory by default (`backend/.storage/resumes`) with generated identifiers rather than user-provided paths. This is suitable for a local MVP; production deployment should use appropriately access-controlled, durable private storage and backup/retention policies.
- **AI provider:** Q&A and interview generation use configured OpenAI-compatible chat-completion settings (`AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`). No provider is bundled and no AI-generated fallback is returned when configuration is absent.
- **CORS:** Defaults are limited to local frontend origins on ports 5173; adjust the allowlist for the deployment environment.

## 6. Authentication and integration assumptions

Inspection did not establish an existing backend auth implementation or a verifiable bearer-token format in the checked-in repository. Therefore, the backend does not parse or trust arbitrary bearer tokens. Configure `STUDENT_TOKEN_VALIDATOR` as `python.module:function_name` for a trusted adapter that validates the token and returns the authenticated student UUID. Without that adapter, protected endpoints fail closed with `503 auth_integration_not_configured`; missing credentials return `401`.

The existing frontend has not been wired to these endpoints in this backend task. Frontend integration must use the project’s actual session/token mechanism and adapt to the response contract. PostgreSQL schema/table/column compatibility should be checked against the deployment database before applying the migration. Local file storage and the real AI provider were not exercised end to end.

## 7. Setup and verification

From the repository root, the documented Windows setup is:

```powershell
py -3.11 -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1
python -m pip install -r backend/requirements.txt

$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
$env:STUDENT_TOKEN_VALIDATOR = "campus_auth.adapter:validate_access_token"
uvicorn app.main:app --app-dir backend --reload
```

Configure `AI_BASE_URL`, `AI_API_KEY`, and `AI_MODEL` only when enabling provider-backed Q&A and interview generation. The README contains further configuration notes.

Commands actually run and observed results:

```text
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
8 passed, 1 warning in 1.11s

python -m compileall -q backend/app backend/tests
completed successfully

git diff --check
completed successfully
```

The single pytest warning was a Starlette deprecation notice concerning its current HTTPX-backed `TestClient`. Tests use SQLite and dependency overrides; they do not prove production PostgreSQL migration behavior, real identity-provider token validation, real external AI-provider behavior, or production storage durability.

## 8. Review checklist / outstanding work

1. Confirm the deployed PostgreSQL schema names and apply/review the new migration.
2. Provide a trusted student-token validation adapter and verify student-ID mapping.
3. Configure private durable storage for deployment, replacing local-disk assumptions if needed.
4. Configure and exercise the approved AI provider, including timeout, privacy, and rate-limit policy.
5. Connect the existing Resume Analyzer frontend and verify its UX against the API contract.
6. Decide whether OCR, retention/deletion, malware scanning, and provider-data handling are required before production.

No Placement Match APIs or functionality were implemented.
