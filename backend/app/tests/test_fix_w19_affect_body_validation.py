"""Regression coverage for affect validation and knowledge body limits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


MAX_KNOWLEDGE_BODY_CHARS = 100_000


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend_dir = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(backend_dir))
    monkeypatch.setenv("WANWEI_API_KEY", "test-key")
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)

    import importlib

    import app.init_db
    import app.main as main_module
    from app.db import close_all

    close_all()
    app.init_db.main()
    importlib.reload(main_module)
    test_client = TestClient(main_module.app, raise_server_exceptions=False)
    yield test_client
    test_client.close()
    close_all()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"x-api-key": "test-key"}


@pytest.mark.parametrize("raw_intensity", ["nan", "inf", "-inf"])
def test_non_finite_intensity_returns_serializable_422(
    client: TestClient,
    auth_headers: dict[str, str],
    raw_intensity: str,
):
    from app.soul.persona import create_persona

    soul_id = create_persona()

    response = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "user_thank", "intensity": raw_intensity},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["detail"] == {
        "error": "invalid_intensity",
        "valid_range": [0.0, 10.0],
    }
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("intensity", [-0.01, 10.01])
def test_out_of_range_intensity_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
    intensity: float,
):
    from app.soul.persona import create_persona

    soul_id = create_persona()

    response = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "user_thank", "intensity": intensity},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "invalid_intensity"


def test_intensity_boundaries_are_accepted_and_zero_is_a_noop(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from app.soul.persona import create_persona

    zero_soul_id = create_persona()
    before = client.get(
        f"/soul/affect/{zero_soul_id}",
        headers=auth_headers,
    ).json()

    zero_response = client.put(
        f"/soul/affect/{zero_soul_id}",
        params={"trigger": "user_thank", "intensity": 0},
        headers=auth_headers,
    )

    assert zero_response.status_code == 200, zero_response.text
    zero_affect = zero_response.json()["affect"]
    assert zero_affect == {
        "pleasure": before["pleasure"],
        "arousal": before["arousal"],
        "dominance": before["dominance"],
        "current_mood": before["current_mood"],
        "mood_intensity": before["mood_intensity"],
    }

    max_soul_id = create_persona()
    max_response = client.put(
        f"/soul/affect/{max_soul_id}",
        params={"trigger": "user_thank", "intensity": 10},
        headers=auth_headers,
    )
    assert max_response.status_code == 200, max_response.text


def test_unknown_and_oversized_triggers_return_422(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from app.soul.persona import create_persona

    soul_id = create_persona()

    unknown = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "untrusted_trigger", "intensity": 1},
        headers=auth_headers,
    )
    oversized = client.put(
        f"/soul/affect/{soul_id}",
        params={"trigger": "x" * 101, "intensity": 1},
        headers=auth_headers,
    )

    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"]["error"] == "invalid_trigger"
    assert oversized.status_code == 422, oversized.text


def test_ghost_soul_returns_404_without_persisting_rows(
    client: TestClient,
    auth_headers: dict[str, str],
):
    from app.db import get_conn

    ghost_soul_id = "soul_ghost_xyz_not_exist"

    response = client.put(
        f"/soul/affect/{ghost_soul_id}",
        params={"trigger": "user_thank", "intensity": 1},
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "error": "soul_not_found",
        "soul_id": ghost_soul_id,
    }
    conn = get_conn()
    assert conn.execute(
        "SELECT 1 FROM affect_state WHERE soul_id=?",
        (ghost_soul_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM affect_events WHERE soul_id=?",
        (ghost_soul_id,),
    ).fetchone() is None


def test_knowledge_body_limit_covers_create_update_and_import(
    client: TestClient,
    auth_headers: dict[str, str],
):
    at_limit = "x" * MAX_KNOWLEDGE_BODY_CHARS
    over_limit = "x" * (MAX_KNOWLEDGE_BODY_CHARS + 1)

    created = client.post(
        "/platform/knowledge/docs",
        json={"title": "boundary", "body": at_limit},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    updated = client.put(
        f"/platform/knowledge/docs/{doc_id}",
        json={"body": at_limit},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text

    create_overflow = client.post(
        "/platform/knowledge/docs",
        json={"title": "too large", "body": over_limit},
        headers=auth_headers,
    )
    update_overflow = client.put(
        f"/platform/knowledge/docs/{doc_id}",
        json={"body": over_limit},
        headers=auth_headers,
    )
    import_overflow = client.post(
        "/platform/knowledge/import",
        json={"items": [{"title": "too large", "body": over_limit}]},
        headers=auth_headers,
    )

    assert create_overflow.status_code == 422, create_overflow.text
    assert update_overflow.status_code == 422, update_overflow.text
    assert import_overflow.status_code == 422, import_overflow.text
    persisted = client.get(
        f"/platform/knowledge/docs/{doc_id}",
        headers=auth_headers,
    )
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["body"] == at_limit
