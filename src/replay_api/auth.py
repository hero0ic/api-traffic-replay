"""Project API tokens.

The plaintext token is shown once when a project is created. Only a hash is
stored. The CLI authenticates with ``Authorization: Bearer <token>``.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from replay_api.config import get_settings
from replay_api.db import get_db
from replay_api.models import Project

bearer_scheme = HTTPBearer(auto_error=False)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    pepper = get_settings().token_pepper.encode("utf-8")
    return hashlib.sha256(pepper + token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def get_project_for_token(
    project_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Project:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    project = db.get(Project, _as_uuid(project_id))
    if project is None or not tokens_match(credentials.credentials, project.token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return project


def _as_uuid(value: str):
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found") from exc
