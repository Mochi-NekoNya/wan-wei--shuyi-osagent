"""身份层解耦测试：owner_id 独立 UUID + key 轮换。

覆盖：
- 首次使用自动注册 identity
- 重复调用返回同一 identity_id
- key 轮换后新 key 继承同一身份
- 旧 key 轮换后失效
- 向后兼容（identity 表未建时回退到 blake2b 派生）
"""
from __future__ import annotations

import importlib
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "identity_test.db")


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setenv("WANWEI_MEMORY_DB", db_path)
    monkeypatch.setenv("WANWEI_API_KEY", "test-owner-key-0123456789abcdef")
    monkeypatch.setenv("WANWEI_ALLOWED_HOSTS", "testserver")
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    from backend.app import init_db
    from backend.app import main as main_module
    from backend.app.db import close_all

    close_all()
    importlib.reload(main_module)
    init_db.main()
    return TestClient(main_module.app, raise_server_exceptions=False)


class TestIdentityRegistration:
    """首次使用自动注册，后续调用返回同一身份。"""

    def test_first_use_registers_identity(self, client):
        r = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        assert r.status_code == 200
        body = r.json()
        assert body["owner_id"].startswith("id_")
        assert body["identity_layer"] == "uuid"

    def test_repeated_calls_same_identity(self, client):
        r1 = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        r2 = client.get("/memory/identity", headers={"x-api-key": "test-owner-key-0123456789abcdef"})
        assert r1.json()["owner_id"] == r2.json()["owner_id"]


class TestKeyRotation:
    """key 轮换：新 key 继承身份，旧 key 失效，历史数据保留。"""

    def test_rotate_preserves_identity(self, client):
        old_key = "test-owner-key-0123456789abcdef"
        new_key = "test-owner-key-rotated-0123456789ab"

        # 先写入一条记忆（旧 key）
        r = client.post(
            "/memory/v2/capsules",
            headers={"x-api-key": old_key},
            json={
                "memory_class": "knowledge",
                "content": {"knowledge_type": "fact", "statement": "轮换前写入"},
                "source_type": "manual_config",
            },
        )
        assert r.status_code == 200
        capsule_id = r.json()["capsule_id"]

        # 轮换
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": old_key},
            json={"new_key": new_key},
        )
        assert r.status_code == 200
        identity_id = r.json()["identity_id"]

        # 新 key 读取同一身份
        r = client.get("/memory/identity", headers={"x-api-key": new_key})
        assert r.json()["owner_id"] == identity_id

        # 新 key 能读到旧 key 写入的记忆
        r = client.get(f"/memory/v2/capsules/{capsule_id}", headers={"x-api-key": new_key})
        assert r.status_code == 200

    def test_old_key_invalid_after_rotation(self, client):
        old_key = "test-owner-key-0123456789abcdef"
        new_key = "test-owner-key-rotated-0123456789ab"

        client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": old_key},
            json={"new_key": new_key},
        )
        # 旧 key 已失效
        r = client.get("/memory/identity", headers={"x-api-key": old_key})
        assert r.status_code == 401

    def test_rotate_requires_min_length(self, client):
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": "test-owner-key-0123456789abcdef"},
            json={"new_key": "short"},
        )
        assert r.status_code == 422


class TestKeyRevocation:
    """独立撤销：不轮换，仅吊销指定 key。

    注意：identity 表已建时，_verify_api_key 优先查注册表。测试用的
    admin_key 必须先通过 rotate 注册为合法 key，才能通过鉴权调用 revoke。
    """

    def test_revoke_unregisters_key(self, client):
        # 注册两个身份：env key（将被撤销）与 admin key（执行撤销）
        env_key = "test-owner-key-0123456789abcdef"
        admin_key = "admin-key-0123456789abcdef01234567"

        # env key 注册
        r = client.get("/memory/identity", headers={"x-api-key": env_key})
        assert r.status_code == 200

        # admin key 通过 rotate 注册（继承同一 identity）
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": env_key},
            json={"new_key": admin_key},
        )
        assert r.status_code == 200

        # 用 admin key 撤销 env key
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": admin_key},
            json={"api_key": env_key},
        )
        assert r.status_code == 200
        assert r.json()["revoked"] is True

        # 被撤销的 key 失效
        r = client.get("/memory/identity", headers={"x-api-key": env_key})
        assert r.status_code == 401

    def test_revoke_rejects_current_key(self, client):
        key = "test-owner-key-0123456789abcdef"
        client.get("/memory/identity", headers={"x-api-key": key})
        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": key},
            json={"api_key": key},
        )
        assert r.status_code == 422

    def test_revoke_unknown_key_404(self, client):
        env_key = "test-owner-key-0123456789abcdef"
        admin_key = "admin-key-0123456789abcdef01234567"

        # 注册 env key，再 rotate 出 admin key
        client.get("/memory/identity", headers={"x-api-key": env_key})
        r = client.post(
            "/memory/identity/rotate",
            headers={"x-api-key": env_key},
            json={"new_key": admin_key},
        )
        assert r.status_code == 200

        r = client.post(
            "/memory/identity/revoke",
            headers={"x-api-key": admin_key},
            json={"api_key": "never-registered-key-0123456789ab"},
        )
        assert r.status_code == 404


class TestBackwardCompatibility:
    """向后兼容：identity 表未建时回退到 blake2b 派生。"""

    def test_legacy_derived_when_table_missing(self, tmp_path, monkeypatch):
        db = str(tmp_path / "legacy.db")
        monkeypatch.setenv("WANWEI_MEMORY_DB", db)
        monkeypatch.setenv("WANWEI_API_KEY", "legacy-key-0123456789abcdef01")
        from backend.app.db import close_all
        from backend.app.security.auth import _derive_legacy_owner_id

        close_all()
        # 不跑 init_db，直接调派生函数
        owner = _derive_legacy_owner_id("legacy-key-0123456789abcdef01")
        assert owner.startswith("api_")
