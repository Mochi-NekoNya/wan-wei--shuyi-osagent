"""
Evolution 模块修复测试 — 裸 assert 和 N+1 查询

验证 evolution.py 的两个硬伤修复：
1. 裸 assert 在 -O 优化模式下被忽略，改为显式 ValueError
2. reflect_task 的 N+1 查询，改为批量 get_capsules_batch

v0.11.1 fix/evolution-assert-and-n1
"""

import pytest
from backend.app.memory_runtime import evolution as ev
from backend.app.memory_runtime import capsule_store as cs


def _write(text: str) -> str:
    return cs.write_capsule(memory_class="knowledge", content={"text": text})["capsule_id"]


# ---------------------------------------------------------------------------
# 裸 assert 修复：显式 ValueError + 友好错误信息
# ---------------------------------------------------------------------------

def test_reinforce_nonexistent_raises_valueerror(isolated_db):
    """reinforce 不存在的 capsule → 抛 ValueError（不是 AssertionError）。"""
    with pytest.raises(ValueError, match="Capsule not found: cap_ghost"):
        ev.reinforce("cap_ghost")


def test_deprecate_nonexistent_raises_valueerror(isolated_db):
    """deprecate 不存在的 capsule → 抛 ValueError。"""
    with pytest.raises(ValueError, match="Capsule not found: cap_ghost"):
        ev.deprecate("cap_ghost")


def test_conflict_mark_nonexistent_raises_valueerror(isolated_db):
    """conflict_mark 不存在的 capsule → 抛 ValueError。"""
    with pytest.raises(ValueError, match="Capsule not found: cap_ghost"):
        ev.conflict_mark("cap_ghost")


def test_supersede_nonexistent_old_raises_valueerror(isolated_db):
    """supersede 不存在的旧 capsule → 抛 ValueError。"""
    with pytest.raises(ValueError, match="Capsule not found: cap_old_ghost"):
        ev.supersede("cap_old_ghost", new_content={"text": "新内容"})


def test_reinforce_existent_succeeds(isolated_db):
    """正常路径：reinforce 存在的 capsule → 成功更新。"""
    cid = _write("待加固的知识")
    result = ev.reinforce(cid, amount=0.2)
    
    assert result["capsule_id"] == cid
    cap = cs.get_capsule(cid)
    assert cap["state"]["lifecycle"] == "reinforced"
    assert cap["state"]["importance_score"] >= 0.7  # 0.5 base + 0.2


# ---------------------------------------------------------------------------
# reflect_task N+1 查询修复：批量 get_capsules_batch
# ---------------------------------------------------------------------------

def test_reflect_task_batch_fetch_reduces_queries(isolated_db):
    """reflect_task 用 get_capsules_batch 批量查询，避免 N+1。
    
    这个测试更多是"代码审查证据"——实际查询次数需要 DB profiler 验证。
    我们验证语义正确性：helpful 加固、misleading 废弃、最终 actions 正确。
    """
    cap_a = _write("有用的记忆 A")
    cap_b = _write("有用的记忆 B")
    cap_c = _write("误导性记忆 C")
    
    result = ev.reflect_task(
        task_id="task_batch_test",
        payload={
            "helpful_memories": [cap_a, cap_b],
            "misleading_memories": [cap_c],
        },
    )
    
    # 验证 actions 记录正确
    actions = result["evolution_actions"]
    assert len(actions) == 3
    assert {"action": "reinforce", "capsule_id": cap_a} in actions
    assert {"action": "reinforce", "capsule_id": cap_b} in actions
    assert {"action": "deprecate", "capsule_id": cap_c} in actions
    
    # 验证实际状态变更
    assert cs.get_capsule(cap_a)["state"]["lifecycle"] == "reinforced"
    assert cs.get_capsule(cap_b)["state"]["lifecycle"] == "reinforced"
    assert cs.get_capsule(cap_c)["state"]["lifecycle"] == "deprecated"


def test_reflect_task_skips_nonexistent_capsules(isolated_db):
    """reflect_task 遇到不存在的 capsule_id → 跳过，不炸。
    
    批量查询后，只对存在的 capsule 执行 reinforce/deprecate。
    """
    cap_real = _write("真实存在的记忆")
    
    result = ev.reflect_task(
        task_id="task_partial_exist",
        payload={
            "helpful_memories": [cap_real, "cap_ghost_1"],
            "misleading_memories": ["cap_ghost_2"],
        },
    )
    
    # 只有真实存在的 capsule 被处理
    actions = result["evolution_actions"]
    assert len(actions) == 1
    assert actions[0] == {"action": "reinforce", "capsule_id": cap_real}
    
    # ghost capsule 被跳过，不在 actions 里
    ghost_ids = [a["capsule_id"] for a in actions]
    assert "cap_ghost_1" not in ghost_ids
    assert "cap_ghost_2" not in ghost_ids


def test_reflect_task_empty_memories_no_crash(isolated_db):
    """reflect_task 没有任何记忆 ID → 空 actions，不崩溃。"""
    result = ev.reflect_task(
        task_id="task_empty",
        payload={
            "helpful_memories": [],
            "misleading_memories": [],
            "new_risks": [],
        },
    )
    
    assert result["evolution_actions"] == []
    assert result["task_id"] == "task_empty"
