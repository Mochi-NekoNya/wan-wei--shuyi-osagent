"""
Affect decay daemon.

Slowly pulls PAD values back toward the soul's baseline personality traits
and attenuates mood_intensity over time.  Intended to run as a background
thread inside the FastAPI lifespan.
"""

import logging
import threading
import time

from ..db import get_conn, transaction
from ..utils.datetime_utils import utc_now_iso_compact
from .state_machine import AffectState, save_affect, _clamp

logger = logging.getLogger(__name__)


def decay_affect(soul_id: str) -> AffectState:
    """
    Execute a single decay step for *one* soul.

    Algorithm:
        pleasure    += (baseline_p - pleasure)    * 0.15
        arousal     += (baseline_a - arousal)     * 0.20
        mood_intensity *= 0.85

    Returns the updated AffectState.
    """
    conn = get_conn()

    # Load baseline from soul_persona
    baseline = conn.execute(
        "SELECT baseline_pleasure, baseline_arousal, baseline_dominance "
        "FROM soul_persona WHERE soul_id=?",
        (soul_id,),
    ).fetchone()

    if baseline is None:
        # Soul does not exist — nothing to decay
        return AffectState()

    # 03-#11: is None 判断——显式配置的 0.0 baseline 不得被 `or` 吃成默认值
    baseline_p = baseline["baseline_pleasure"] if baseline["baseline_pleasure"] is not None else 0.6
    baseline_a = baseline["baseline_arousal"] if baseline["baseline_arousal"] is not None else 0.4
    baseline_d = baseline["baseline_dominance"] if baseline["baseline_dominance"] is not None else 0.5

    # Load current affect
    row = conn.execute(
        "SELECT pleasure, arousal, dominance, current_mood, mood_intensity "
        "FROM affect_state WHERE soul_id=?",
        (soul_id,),
    ).fetchone()

    if row is None:
        # 04-#04: 竞态修复——两个线程同时发现 row is None 会导致重复 INSERT。
        # 用 INSERT OR IGNORE 原子性地"创建或跳过"，然后重新查询确保读到数据。
        ts = utc_now_iso_compact()
        state = AffectState(
            pleasure=baseline_p, arousal=baseline_a, dominance=baseline_d
        )
        with transaction() as txn:
            cursor = txn.execute(
                "INSERT OR IGNORE INTO affect_state(soul_id, pleasure, arousal, dominance, "
                "current_mood, mood_intensity, updated_at) VALUES (?,?,?,?,?,?,?)",
                (soul_id, state.pleasure, state.arousal, state.dominance,
                 state.current_mood, state.mood_intensity, ts),
            )
            # 权威事实来源：直接问数据库"本线程是否真的插入了这一行"。
            # 不用"落库值是否等于 baseline"来反推——那是靠数值巧合推断控制流，
            # 一旦播种初值的构造方式变化（例如将来播种时带上非 baseline 的
            # mood_intensity）判断就会失效。rowcount 与数值无关，恒定可靠。
            did_insert = cursor.rowcount == 1
        if did_insert:
            # 本线程播种成功，本轮不衰减（刚出生的状态没有可衰减的历史）
            return state
        # 并发线程抢先插入了：重新查询它落库的真实值，继续正常衰减
        row = conn.execute(
            "SELECT pleasure, arousal, dominance, current_mood, mood_intensity "
            "FROM affect_state WHERE soul_id=?",
            (soul_id,),
        ).fetchone()
        if row is None:
            # 理论上不应发生：INSERT OR IGNORE 未插入意味着行已存在，此时查不到
            # 说明数据库层一致性崩坏（或该行在两次语句之间被删除）
            raise RuntimeError(
                f"Internal error: affect_state for soul_id={soul_id} vanished after INSERT OR IGNORE. "
                "This indicates a critical database consistency issue."
            )

    pleasure = row["pleasure"]
    arousal = row["arousal"]
    dominance = row["dominance"]
    mood_intensity = row["mood_intensity"]

    # Decay toward baseline
    pleasure = _clamp(pleasure + (baseline_p - pleasure) * 0.15)
    arousal = _clamp(arousal + (baseline_a - arousal) * 0.20)
    dominance = _clamp(dominance + (baseline_d - dominance) * 0.15)
    mood_intensity = _clamp(mood_intensity * 0.85)

    # Mood drifts toward calm as intensity fades
    current_mood = row["current_mood"]
    if mood_intensity < 0.15 and current_mood not in ("calm", "neutral"):
        current_mood = "calm"

    state = AffectState(
        pleasure=pleasure,
        arousal=arousal,
        dominance=dominance,
        current_mood=current_mood,
        mood_intensity=mood_intensity,
    )
    save_affect(soul_id, state)
    return state


def _decay_all_souls() -> None:
    """Decay every soul that has an affect_state row."""
    conn = get_conn()
    rows = conn.execute("SELECT soul_id FROM affect_state").fetchall()
    for row in rows:
        try:
            decay_affect(row["soul_id"])
        except Exception as exc:
            # Never let one soul's decay kill the daemon（降级但留痕）
            logger.warning("decay_affect failed for soul_id=%s: %s", row["soul_id"], exc)


def run_decay_daemon(interval_seconds: int = 1800, stop_event: threading.Event | None = None) -> None:
    """
    Blocking decay loop.  Call from a daemon thread.

    Example (inside FastAPI lifespan):
        stop = threading.Event()
        t = threading.Thread(target=lambda: run_decay_daemon(1800, stop), daemon=True)
        t.start()
        ...
        stop.set()
    """
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        stop_event.wait(timeout=interval_seconds)
        if stop_event.is_set():
            break
        try:
            _decay_all_souls()
        except Exception as exc:
            # The daemon must survive DB hiccups（降级但留痕）
            logger.warning("decay daemon iteration failed: %s", exc)
