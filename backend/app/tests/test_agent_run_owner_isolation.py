"""Regression tests for per-API-key agent run ownership.

从 upstream-jianghe 移植，适配 main 约定：双 key 鉴权经
``backend.app.security.auth._verify_api_key`` monkeypatch 实现。

适配说明：agents 域的 owner 隔离为 main 既有行为（有属主的 agent/team/run
跨属主 404，run 创建返回含 owner_id 的完整对象）；subagent 子 run / floating
workspace / ownerless 存量记录保持 main 兼容语义（ownerless 对任何已鉴权调用方
可见，见 agents.py 可见性函数的有意设计）。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


OWNER_A = "owner-a-key"
OWNER_B = "owner-b-key"
HEADERS_A = {"x-api-key": OWNER_A}
HEADERS_B = {"x-api-key": OWNER_B}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WANWEI_API_KEY", OWNER_A)
    monkeypatch.setenv("WANWEI_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("WANWEI_PLATFORM_DIR", str(tmp_path / "platform"))
    monkeypatch.delenv("WANWEI_PRODUCTION", raising=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

    import backend.app.security.auth as auth
    import backend.app.init_db
    import backend.app.app_runtime as runtime_mod
    import backend.app.main as main_mod

    verify = lambda provided: provided in {OWNER_A, OWNER_B}  # noqa: E731
    monkeypatch.setattr(auth, "_verify_api_key", verify)

    importlib.reload(runtime_mod)
    importlib.reload(main_mod)
    backend.app.init_db.main()
    with TestClient(main_mod.app, raise_server_exceptions=False) as test_client:
        yield test_client


def _create_agent(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/platform/agents",
        json={"name": "owner-isolation", "gear": "human_review", "depth": "low"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_run(client: TestClient, headers: dict[str, str], agent_id: str) -> str:
    response = client.post(
        "/platform/agents/run",
        json={"agent_id": agent_id, "task": "owner-isolation"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    # main 契约：run 创建返回完整 run（含 owner_id，未走 public 脱敏）
    assert isinstance(payload.get("owner_id"), str) and payload["owner_id"]
    return payload["id"]


def test_run_reads_and_mutations_are_owner_scoped(client):
    agent_id = _create_agent(client, HEADERS_A)
    run_id = _create_run(client, HEADERS_A, agent_id)

    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_A).status_code == 200
    listed_a = client.get("/platform/agents/runs", headers=HEADERS_A)
    assert listed_a.status_code == 200
    assert run_id in {item["id"] for item in listed_a.json()["items"]}

    # A second valid principal cannot discover or mutate the first principal's run.
    assert client.get(f"/platform/agents/runs/{run_id}", headers=HEADERS_B).status_code == 404
    listed_b = client.get("/platform/agents/runs", headers=HEADERS_B)
    assert listed_b.status_code == 200
    assert run_id not in {item["id"] for item in listed_b.json()["items"]}
    assert client.post(f"/platform/agents/runs/{run_id}/approve", headers=HEADERS_B).status_code == 404
    assert client.post(f"/platform/agents/runs/{run_id}/cancel", headers=HEADERS_B).status_code == 404

    # main 的 /subagent 只校验 parent 存在性、不校验属主（既有行为，不在 C3 范围）。
    missing_attempt = client.post(
        "/platform/agents/subagent",
        json={"task": "no-parent", "parent_run_id": "run_missing_parent"},
        headers=HEADERS_B,
    )
    assert missing_attempt.status_code == 404, missing_attempt.text


def test_subagent_and_floating_workspace_follow_ownerless_semantics(client):
    """main 现状锁定：/subagent 产生的子 run 不继承属主（ownerless），floating
    workspace 不按属主过滤；ownerless 记录对所有已鉴权调用方可见。"""
    agent_id = _create_agent(client, HEADERS_A)
    parent_id = _create_run(client, HEADERS_A, agent_id)
    child = client.post(
        "/platform/agents/subagent",
        json={"task": "child", "parent_run_id": parent_id},
        headers=HEADERS_A,
    )
    assert child.status_code == 201, child.text
    child_payload = child.json()
    child_id = child_payload["run"]["id"]
    session_id = child_payload["session"]["id"]
    assert child_payload["run"].get("owner_id") is None
    assert "owner_id" not in child_payload["session"]

    # 子 run / 会话 ownerless：任何已鉴权调用方均可见（兼容策略）
    workspace_b = client.get("/platform/agents/workspace/floating", headers=HEADERS_B)
    assert workspace_b.status_code == 200
    assert session_id in {item["id"] for item in workspace_b.json()["items"]}
    assert client.get(f"/platform/agents/runs/{child_id}", headers=HEADERS_B).status_code == 200

    # parent 存在性校验仍生效：不存在的 parent → 404
    missing = client.post(
        "/platform/agents/subagent",
        json={"task": "no-parent", "parent_run_id": "run_missing"},
        headers=HEADERS_B,
    )
    assert missing.status_code == 404, missing.text


def test_owner_isolation_and_ownerless_legacy_visibility(client):
    """隔离核心 + 兼容策略锁定：有属主的 agent/team 跨属主 404；模拟存量
    ownerless 记录（移除 owner_id）则对任何已鉴权调用方可见（main 有意设计，
    避免升级后既有数据集体 404）。"""
    from backend.app.platform_api import agents as agents_mod

    # 有属主 agent：跨属主 404（隔离核心）
    agent_id = _create_agent(client, HEADERS_A)
    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_B).status_code == 404

    # 模拟存量 ownerless agent：所有已鉴权调用方可见（兼容策略）
    raw_agent = agents_mod._agents.get(agent_id)  # noqa: SLF001
    raw_agent.pop("owner_id", None)
    agents_mod._agents.set(agent_id, raw_agent)  # noqa: SLF001
    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/{agent_id}", headers=HEADERS_B).status_code == 200

    # 有属主 team：跨属主 404
    team = client.post(
        "/platform/agents/teams",
        json={"name": "legacy-team", "member_ids": [agent_id]},
        headers=HEADERS_A,
    )
    assert team.status_code == 201, team.text
    team_id = team.json()["id"]
    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_B).status_code == 404

    # 模拟存量 ownerless team：所有已鉴权调用方可见
    raw_team = agents_mod._teams_map().get(team_id)  # noqa: SLF001
    raw_team.pop("owner_id", None)
    agents_mod._save_team(team_id, raw_team)  # noqa: SLF001
    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_A).status_code == 200
    assert client.get(f"/platform/agents/teams/{team_id}", headers=HEADERS_B).status_code == 200
