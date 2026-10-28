"""Shared fixtures. API tests use a temp SQLite database, not Docker Postgres."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from replay_api.config import get_settings
from replay_api.db import configure_database, create_tables, drop_tables
from replay_api.llm import set_provider_override
from replay_api.main import app


@pytest.fixture
def api_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("TOKEN_PEPPER", "test-pepper")
    monkeypatch.setenv("CREATE_TABLES_ON_STARTUP", "false")
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    set_provider_override(None)

    database_url = f"sqlite:///{tmp_path / 'replay.db'}"
    configure_database(database_url)
    create_tables()
    with TestClient(app) as client:
        yield client
    drop_tables()
    set_provider_override(None)
    get_settings.cache_clear()
