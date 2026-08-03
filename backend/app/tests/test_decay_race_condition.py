"""
Decay daemon 竞态条件修复测试

验证 decay_affect 在并发场景下的 Check-Then-Act 竞态修复：
- 旧实现：两个线程同时发现 affect_state 不存在 → 两次 INSERT → UNIQUE 冲突炸掉
- 新实现：INSERT OR IGNORE + 重新查询 → 原子性地"创建或跳过" → 无冲突

v0.11.1 fix/decay-affect-race-condition
"""

import threading
import pytest
from backend.app.affect.decay_daemon import decay_affect
from backend.app.affect.state_machine import AffectState, save_affect
from backend.app.soul.persona import create_persona, update_persona


def test_decay_affect_concurrent_insert_no_conflict(isolated_db):
    """并发场景：多个线程同时为同一个 soul 初次调用 decay_affect → 无冲突。

    旧实现（裸 INSERT）：
        - 线程A: SELECT ... → None
        - 线程B: SELECT ... → None（A 还没插入）
        - 线程A: INSERT → 成功
        - 线程B: INSERT → 💥 UNIQUE constraint failed: affect_state.soul_id
    
    新实现（INSERT OR IGNORE + 重查）：
        - 线程A: SELECT ... → None
        - 线程B: SELECT ... → None
        - 线程A: INSERT OR IGNORE → 插入成功
        - 线程B: INSERT OR IGNORE → 静默跳过（UNIQUE 冲突被 OR IGNORE 吃掉）
        - A、B 各自重新查询 → 都读到同一行，继续衰减
    """
    sid = create_persona("soul_race_test")
    update_persona(sid, baseline_pleasure=0.5, baseline_arousal=0.5, baseline_dominance=0.5)
    
    # 确保 affect_state 表里没有这个 soul 的记录
    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM affect_state WHERE soul_id=?", (sid,))
    conn.commit()
    
    results = []
    exceptions = []
    
    def worker():
        try:
            state = decay_affect(sid)
            results.append(state)
        except Exception as exc:
            exceptions.append(exc)
    
    # 启动 10 个线程并发调用 decay_affect（首次插入）
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # 关键验证：无异常（旧实现会有多个 UNIQUE constraint 异常）
    assert len(exceptions) == 0, f"并发插入出现异常：{exceptions}"
    
    # 所有线程都成功返回了 AffectState
    assert len(results) == 10
    
    # affect_state 表里只有一条记录（INSERT OR IGNORE 原子性保证）
    rows = conn.execute("SELECT COUNT(*) FROM affect_state WHERE soul_id=?", (sid,)).fetchone()
    assert rows[0] == 1


def test_decay_affect_concurrent_update_safe(isolated_db):
    """并发场景：多个线程同时对已存在的 affect_state 做衰减 → 无冲突。
    
    这个场景旧实现本身就安全（UPDATE 操作不会冲突），但验证新实现没破坏。
    """
    sid = create_persona("soul_update_race")
    update_persona(sid, baseline_pleasure=0.0, baseline_arousal=0.0, baseline_dominance=0.0)
    save_affect(
        sid,
        AffectState(pleasure=1.0, arousal=1.0, dominance=1.0, current_mood="excited", mood_intensity=1.0),
    )
    
    results = []
    exceptions = []
    
    def worker():
        try:
            state = decay_affect(sid)
            results.append(state)
        except Exception as exc:
            exceptions.append(exc)
    
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(exceptions) == 0
    assert len(results) == 5
    
    # 最后一次衰减的结果被持久化（顺序不确定，但至少有一次衰减生效了）
    from backend.app.affect import load_affect
    final_state = load_affect(sid)
    # 至少做了一次衰减：pleasure 从 1.0 → 0.85（向 0.0 baseline 靠近 15%）
    assert final_state.pleasure < 1.0


def test_decay_affect_insert_or_ignore_idempotent(isolated_db):
    """INSERT OR IGNORE 是幂等的：重复调用只插入一次。"""
    sid = create_persona("soul_idempotent")
    update_persona(sid, baseline_pleasure=0.6, baseline_arousal=0.4, baseline_dominance=0.5)
    
    from backend.app.db import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM affect_state WHERE soul_id=?", (sid,))
    conn.commit()
    
    # 连续调用 3 次（第一次插入，后两次跳过）
    state1 = decay_affect(sid)
    state2 = decay_affect(sid)
    state3 = decay_affect(sid)
    
    # 表里只有一条记录
    rows = conn.execute("SELECT COUNT(*) FROM affect_state WHERE soul_id=?", (sid,)).fetchone()
    assert rows[0] == 1
    
    # 后续调用做了衰减（不是重复返回初始状态）
    # 第一次返回初始状态（0.6, 0.4, 0.5），第二次开始衰减
    assert state1.pleasure == 0.6
    # state2 和 state3 应该已经有衰减痕迹了（或者如果 baseline 就是当前值，则不变）
    # 这里只验证"能正常运行不炸"
