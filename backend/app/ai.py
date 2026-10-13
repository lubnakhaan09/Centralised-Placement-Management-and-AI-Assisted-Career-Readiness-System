"""OpenAI-compatible provider adapter for resume Q&A and interview questions."""
import json

import httpx

from .config import get_settings


class AIProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _complete(system_prompt: str, user_prompt: str) -> str:
    settings = get_settings()
    if not settings.ai_base_url or not settings.ai_api_key or not settings.ai_model:
        raise AIProviderError("ai_provider_not_configured", "Resume Q&A and interview generation are unavailable because the AI provider is not configured.", 503)
    endpoint = settings.ai_base_url.rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            json={
                "model": settings.ai_model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=settings.ai_timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("provider content is not text")
        return content
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AIProviderError("ai_provider_error", "The configured AI provider failed or returned an invalid response.") from exc


def answer_resume_question(extracted_text: str, question: str, job_description: str | None = None) -> dict:
    system = (
        "Answer questions using only the provided resume and optional job description. "
        "Do not invent candidate experience, qualifications, or facts. If the resume does not contain the answer, say so. "
        'Return only JSON with keys "answer" (string) and "evidence" (array of short exact resume excerpts).'
    )
    user = json.dumps({"resume_text": extracted_text[:100_000], "question": question, "job_description": job_description}, ensure_ascii=False)
    try:
        result = json.loads(_complete(system, user))
        answer = result["answer"]
        evidence = result.get("evidence", [])
        if not isinstance(answer, str) or not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ValueError("unexpected answer schema")
        return {"answer": answer, "evidence": evidence[:10]}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise AIProviderError("ai_provider_invalid_output", "The configured AI provider returned an invalid answer format.") from exc


def generate_interview_questions(extracted_text: str, categories: list[str], count: int, difficulty: str, job_description: str | None = None) -> list[dict]:
    system = (
        "Generate interview questions grounded in the provided resume and optional target job description. "
        "Do not claim the candidate has facts not present in the resume. Return only JSON with key "
        '"questions", an array of objects with "category", "question", and "rationale".'
    )
    user = json.dumps({
        "resume_text": extracted_text[:100_000], "categories": categories,
        "count_per_category": count, "difficulty": difficulty, "job_description": job_description,
    }, ensure_ascii=False)
    try:
        items = json.loads(_complete(system, user))["questions"]
        allowed = set(categories)
        if not isinstance(items, list):
            raise ValueError("questions must be an array")
        clean = []
        for item in items:
            category, question = item["category"], item["question"]
            rationale = item.get("rationale")
            if category not in allowed or not isinstance(question, str) or (rationale is not None and not isinstance(rationale, str)):
                raise ValueError("invalid question entry")
            clean.append({"category": category, "question": question, "rationale": rationale})
        return clean[: len(categories) * count]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise AIProviderError("ai_provider_invalid_output", "The configured AI provider returned an invalid question format.") from exc
