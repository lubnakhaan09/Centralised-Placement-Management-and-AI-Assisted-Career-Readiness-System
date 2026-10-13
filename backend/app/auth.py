"""Student authentication boundary for the host application's token validator.

The repository contains no access-token implementation. This module therefore
requires an explicitly configured adapter and never accepts an unverified ID.
"""
from dataclasses import dataclass
import importlib
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import StudentProfile

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class StudentPrincipal:
    user_id: UUID
    student_id: UUID


class TokenValidationError(Exception):
    """The configured CampusConnect token adapter may raise this for bad tokens."""


def _resolve_user_id(token: str) -> UUID:
    adapter_path = get_settings().student_token_validator
    if not adapter_path:
        raise HTTPException(status_code=503, detail={"code": "auth_integration_not_configured", "message": "Student authentication is not connected to the CampusConnect token validator."})
    try:
        module_name, function_name = adapter_path.rsplit(":", 1)
        validator = getattr(importlib.import_module(module_name), function_name)
        result = validator(token)
        value = result.get("user_id") if isinstance(result, dict) else getattr(result, "user_id", result)
        return UUID(str(value))
    except TokenValidationError:
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "The access token is invalid or expired."}) from None
    except HTTPException:
        raise
    except Exception:
        # Do not expose validator internals or treat a misconfigured adapter as valid auth.
        raise HTTPException(status_code=503, detail={"code": "auth_integration_unavailable", "message": "The CampusConnect token validator could not be used."}) from None


def get_current_student(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> StudentPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message": "Provide a valid CampusConnect bearer token."})
    user_id = _resolve_user_id(credentials.credentials)
    try:
        profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user_id))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail={"code": "database_unavailable", "message": "Student profile could not be loaded."}) from None
    if profile is None:
        raise HTTPException(status_code=403, detail={"code": "student_profile_required", "message": "This account does not have a student profile."})
    return StudentPrincipal(user_id=user_id, student_id=profile.student_id)
