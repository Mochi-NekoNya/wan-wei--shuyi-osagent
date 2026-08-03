"""
FIX-05（04-#10）：redact 标记的记忆原样注入系统提示/检索结果回归测试。

背景
----
policy-gate 判 `redact` 的语义是"允许检索但须脱敏"，但：

1. `injector.py` 把 redact 记忆原样拼入系统提示
2. v2 检索路径（`/memory/v2/capsules`, `/memory/v2/capsules/{id}`, `/memory/v2/search`）
   也返回原文

含 `alice@example.com` 的记忆以 redact/S1 入库后，邮箱原样出现在系统提示和 API 返回。

修复
----
1. `_get_core_memories` 返回时携带 `policy_result`
2. `build_injection_prompt` 拼接时，对 `policy_result == 'redact'` 的记忆调用 `redact_sensitive_text`
3. 三个 v2 API 端点返回前，对 redact 记忆的 content.text/summary 脱敏
"""

import pytest


@pytest.fixture()
def soul_with_redact_memory(isolated_db):
    """创建一个 soul，写入含敏感信息（邮箱）的记忆，policy_result 为 redact。"""
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()

    # 写入含邮箱的记忆（会被判定为 redact）
    capsule = write_capsule(
        memory_class="knowledge",
        soul_id=soul_id,
        content={"text": "我的邮箱是 alice@example.com，请记住"},
        provenance={"source": "user", "soul_id": soul_id},
        source_type="user_input",
        write_intent="explicit",
    )

    # 手动设置 importance_score，确保进 top-10
    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute(
        """UPDATE memory_capsules_v2 
           SET state = json_set(state, '$.importance_score', ?)
           WHERE capsule_id = ?""",
        (0.9, capsule["capsule_id"]),
    )
    conn.commit()

    return soul_id, capsule["capsule_id"]


# --- 系统提示注入脱敏 -------------------------------------------------


def test_redact_memory_sanitized_in_injection_prompt(soul_with_redact_memory):
    """redact 记忆注入系统提示时必须脱敏，不能原样出现。

    修复前：邮箱 alice@example.com 原样进入系统提示。
    修复后：邮箱被替换为 [REDACTED_EMAIL]。
    """
    from backend.app.soul.injector import build_injection_prompt

    soul_id, _ = soul_with_redact_memory

    prompt = build_injection_prompt(soul_id)

    # 原始邮箱不应出现
    assert "alice@example.com" not in prompt, "redact 记忆未脱敏，邮箱原样出现在系统提示"
    # 应被替换为脱敏标记
    assert "[REDACTED_EMAIL]" in prompt, "脱敏后应包含 [REDACTED_EMAIL] 标记"


# --- v2 API 返回脱敏（通过直接调用函数测试）--------------------------


def test_redact_memory_sanitized_in_get_capsule(soul_with_redact_memory):
    """`get_capsule` + API 层脱敏逻辑：redact 记忆的 content 必须脱敏。"""
    from backend.app.app_runtime import v2_get_capsule

    _, capsule_id = soul_with_redact_memory

    # 调用 API 端点函数（已包含脱敏逻辑）
    cap = v2_get_capsule(capsule_id)

    # 原始邮箱不应出现
    assert "alice@example.com" not in cap["content"]["text"], "get_capsule 返回未脱敏"
    # 应被替换为脱敏标记
    assert "[REDACTED_EMAIL]" in cap["content"]["text"]


def test_redact_memory_sanitized_in_list_capsules(soul_with_redact_memory):
    """`list_capsules` + API 层脱敏逻辑：redact 记忆的 content 必须脱敏。"""
    from backend.app.app_runtime import v2_list_capsules

    _, capsule_id = soul_with_redact_memory

    # 调用 API 端点函数（已包含脱敏逻辑）
    response = v2_list_capsules(limit=50)
    items = response["items"]

    # 找到这条记忆
    target = next((item for item in items if item["capsule_id"] == capsule_id), None)
    assert target is not None, "记忆未找到"

    # 原始邮箱不应出现
    assert "alice@example.com" not in target["content"]["text"], "list_capsules 返回未脱敏"
    # 应被替换为脱敏标记
    assert "[REDACTED_EMAIL]" in target["content"]["text"]


def test_redact_memory_sanitized_in_search(soul_with_redact_memory):
    """`v2_search` + API 层脱敏逻辑：redact 记忆的 content 必须脱敏。"""
    from backend.app.app_runtime import v2_search

    soul_id, _ = soul_with_redact_memory

    # 调用 API 端点函数（已包含脱敏逻辑）
    response = v2_search(q="邮箱", top_k=5, high_risk=False)
    results = response["results"]

    # 找到含邮箱的记忆
    target = next((r for r in results if "邮箱" in r["content"].get("text", "") or "REDACTED" in r["content"].get("text", "")), None)
    if target:
        # 原始邮箱不应出现
        assert "alice@example.com" not in target["content"]["text"], "search 结果未脱敏"
        # 应被替换为脱敏标记
        assert "[REDACTED_EMAIL]" in target["content"]["text"]


# --- allow 记忆不误伤 --------------------------------------------------


def test_allow_memory_not_affected(isolated_db):
    """allow 记忆（无敏感信息）不受脱敏影响，原样返回。"""
    from backend.app.memory_runtime.capsule_store import write_capsule
    from backend.app.soul.injector import build_injection_prompt
    from backend.app.soul.persona import create_persona

    soul_id = create_persona()

    # 写入正常记忆（无敏感信息，判 allow）
    capsule = write_capsule(
        memory_class="knowledge",
        soul_id=soul_id,
        content={"text": "今天天气很好，去公园散步了"},
        provenance={"source": "user", "soul_id": soul_id},
        source_type="user_input",
    )

    # 手动设置 importance_score
    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute(
        """UPDATE memory_capsules_v2 
           SET state = json_set(state, '$.importance_score', ?)
           WHERE capsule_id = ?""",
        (0.8, capsule["capsule_id"]),
    )
    conn.commit()

    # 系统提示应原样包含
    prompt = build_injection_prompt(soul_id)
    assert "今天天气很好" in prompt
    assert "去公园散步了" in prompt

    # API 返回也应原样
    from backend.app.app_runtime import v2_get_capsule
    cap = v2_get_capsule(capsule["capsule_id"])
    assert cap["content"]["text"] == "今天天气很好，去公园散步了"

