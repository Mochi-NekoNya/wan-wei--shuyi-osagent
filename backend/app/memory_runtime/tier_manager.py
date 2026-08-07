"""Memory tier management: promotion/demotion logic for short/mid/long-term memory.

对应 GitHub issue #56: 短期/中期记忆自动流转机制
赛题要求(6): 兼容与记忆模块中短期、中期记忆间的数据流转
"""
from datetime import datetime, timedelta
from typing import Any
import json

from ..db import get_conn
from ..utils.datetime_utils import utc_now_iso_compact


TIER_MIGRATION_NAME = "memory_tier_column_v1"


def migrate_tier_column() -> bool:
    """Add 'tier' column to memory_capsules_v2 table.
    
    Migration strategy:
    - Default all existing capsules to 'working' tier
    - Create index on (tier) for efficient filtering
    
    Returns:
        True if migration was applied, False if already applied.
    """
    with get_conn() as conn:
        # Ensure migrations table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_schema_migrations(
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        
        # Check if already applied
        if conn.execute(
            "SELECT 1 FROM memory_schema_migrations WHERE name=?",
            (TIER_MIGRATION_NAME,),
        ).fetchone():
            return False
        
        try:
            conn.execute("BEGIN IMMEDIATE")
            
            # Double-check (race protection)
            if conn.execute(
                "SELECT 1 FROM memory_schema_migrations WHERE name=?",
                (TIER_MIGRATION_NAME,),
            ).fetchone():
                conn.commit()
                return False
            
            # Check if 'tier' column already exists (idempotent)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}
            if "tier" not in columns:
                conn.execute(
                    "ALTER TABLE memory_capsules_v2 "
                    "ADD COLUMN tier TEXT NOT NULL DEFAULT 'working'"
                )
            
            # Create index on (tier, lifecycle)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_capsule_tier "
                "ON memory_capsules_v2(tier, lifecycle)"
            )
            
            # Record migration
            conn.execute(
                "INSERT INTO memory_schema_migrations(name, applied_at) VALUES (?,?)",
                (TIER_MIGRATION_NAME, utc_now_iso_compact()),
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"tier column migration failed: {e}") from e


def tier_promote(capsule_id: str, to_tier: str, reason: str, trigger_source: str = "manual") -> dict[str, Any]:
    """Promote a capsule to a higher tier.
    
    Tier流转顺序: working → short_term → medium_term → long_term
    可跳档（如 working → long_term）。
    
    Args:
        capsule_id: Capsule ID to promote
        to_tier: Target tier (short_term/medium_term/long_term)
        reason: Human-readable promotion reason
        trigger_source: 'manual' / 'auto_promote' / 'workflow_callback'
    
    Returns:
        Updated capsule state with tier transition info
    
    Raises:
        ValueError: If to_tier is invalid or capsule not found
    """
    valid_tiers = {"working", "short_term", "medium_term", "long_term"}
    if to_tier not in valid_tiers:
        raise ValueError(f"Invalid to_tier: {to_tier}, must be one of {valid_tiers}")
    
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Capsule {capsule_id} not found")
        
        from_tier = row[0]
        if from_tier == to_tier:
            # Already at target tier, no-op
            return {
                "capsule_id": capsule_id,
                "from_tier": from_tier,
                "to_tier": to_tier,
                "changed": False,
                "reason": "already_at_target_tier",
            }
        
        # Update tier
        conn.execute(
            "UPDATE memory_capsules_v2 SET tier=?, updated_at=? WHERE capsule_id=?",
            (to_tier, utc_now_iso_compact(), capsule_id),
        )
        
        # TODO(#56): Write to tier_transition_log (will be added in step 6)
        # For now, just audit via return value
        
        conn.commit()
        return {
            "capsule_id": capsule_id,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "changed": True,
            "reason": reason,
            "trigger_source": trigger_source,
            "transitioned_at": utc_now_iso_compact(),
        }


def tier_demote(capsule_id: str, to_tier: str, reason: str, trigger_source: str = "manual") -> dict[str, Any]:
    """Demote a capsule to a lower tier.
    
    降级场景：长时间未访问、空间回收、用户主动 forget。
    
    Args:
        capsule_id: Capsule ID to demote
        to_tier: Target tier (working/short_term/medium_term)
        reason: Human-readable demotion reason
        trigger_source: 'manual' / 'auto_demote' / 'cleanup'
    
    Returns:
        Updated capsule state with tier transition info
    
    Raises:
        ValueError: If to_tier is invalid or capsule not found
    """
    valid_tiers = {"working", "short_term", "medium_term", "long_term"}
    if to_tier not in valid_tiers:
        raise ValueError(f"Invalid to_tier: {to_tier}, must be one of {valid_tiers}")
    
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Capsule {capsule_id} not found")
        
        from_tier = row[0]
        if from_tier == to_tier:
            return {
                "capsule_id": capsule_id,
                "from_tier": from_tier,
                "to_tier": to_tier,
                "changed": False,
                "reason": "already_at_target_tier",
            }
        
        # Update tier
        conn.execute(
            "UPDATE memory_capsules_v2 SET tier=?, updated_at=? WHERE capsule_id=?",
            (to_tier, utc_now_iso_compact(), capsule_id),
        )
        
        conn.commit()
        return {
            "capsule_id": capsule_id,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "changed": True,
            "reason": reason,
            "trigger_source": trigger_source,
            "transitioned_at": utc_now_iso_compact(),
        }


# Auto-promotion/demotion rules (configurable)
PROMOTION_RULES = {
    "working → short_term": {
        "min_usage_count": 2,
        "min_importance": 0.4,
        "min_age_hours": 1,
    },
    "short_term → medium_term": {
        "min_usage_count": 5,
        "min_importance": 0.5,
        "min_age_days": 3,
    },
    "medium_term → long_term": {
        "min_usage_count": 10,
        "min_importance": 0.7,
        "min_age_days": 14,
    },
}

DEMOTION_RULES = {
    "medium_term → short_term": {
        "max_idle_days": 90,
    },
    "short_term → working": {
        "max_idle_days": 30,
    },
}


def _parse_iso_timestamp(ts: str):
    """Parse ISO timestamp (compact or standard format)."""
    from datetime import datetime
    # Handle compact format: 20260807T123456Z
    if "T" in ts and len(ts) == 16 and ts.endswith("Z"):
        return datetime.strptime(ts, "%Y%m%dT%H%M%SZ")
    # Standard ISO format
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_capsules_eligible_for_promotion(from_tier: str, to_tier: str):
    """Query capsules eligible for promotion based on rules."""
    from datetime import datetime, timedelta
    rule_key = f"{from_tier} → {to_tier}"
    if rule_key not in PROMOTION_RULES:
        return []
    
    rule = PROMOTION_RULES[rule_key]
    min_usage = rule.get("min_usage_count", 0)
    min_importance = rule.get("min_importance", 0.0)
    min_age_hours = rule.get("min_age_hours")
    min_age_days = rule.get("min_age_days")
    
    now = datetime.utcnow()
    if min_age_hours:
        cutoff = now - timedelta(hours=min_age_hours)
    elif min_age_days:
        cutoff = now - timedelta(days=min_age_days)
    else:
        cutoff = now
    
    cutoff_iso = cutoff.strftime("%Y%m%dT%H%M%SZ")
    
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT capsule_id, tier, created_at, state FROM memory_capsules_v2 WHERE tier = ? AND created_at <= ?",
            (from_tier, cutoff_iso),
        ).fetchall()
    
    candidates = []
    for row in rows:
        capsule_id, tier, created_at, state_json = row
        state = json.loads(state_json) if state_json else {}
        usage_count = state.get("usage_count", 0)
        importance = state.get("importance", 0.5)
        
        if usage_count >= min_usage and importance >= min_importance:
            candidates.append({
                "capsule_id": capsule_id,
                "tier": tier,
                "created_at": created_at,
                "usage_count": usage_count,
                "importance": importance,
            })
    
    return candidates


def get_capsules_eligible_for_demotion(from_tier: str, to_tier: str):
    """Query capsules eligible for demotion (stale, low usage)."""
    from datetime import datetime, timedelta
    rule_key = f"{from_tier} → {to_tier}"
    if rule_key not in DEMOTION_RULES:
        return []
    
    rule = DEMOTION_RULES[rule_key]
    max_idle_days = rule.get("max_idle_days", 90)
    
    now = datetime.utcnow()
    idle_cutoff = now - timedelta(days=max_idle_days)
    idle_cutoff_iso = idle_cutoff.strftime("%Y%m%dT%H%M%SZ")
    
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT capsule_id, tier, updated_at FROM memory_capsules_v2 WHERE tier = ? AND updated_at <= ?",
            (from_tier, idle_cutoff_iso),
        ).fetchall()
    
    return [{"capsule_id": row[0], "tier": row[1], "updated_at": row[2]} for row in rows]


def promote_eligible_capsules():
    """Auto-promote capsules based on rules (called by scheduler)."""
    summary = {"promoted": [], "total": 0}
    
    transitions = [
        ("working", "short_term"),
        ("short_term", "medium_term"),
        ("medium_term", "long_term"),
    ]
    
    for from_tier, to_tier in transitions:
        candidates = get_capsules_eligible_for_promotion(from_tier, to_tier)
        promoted_count = 0
        
        for cap in candidates:
            try:
                result = tier_promote(
                    cap["capsule_id"],
                    to_tier=to_tier,
                    reason=f"auto: usage={cap['usage_count']}, importance={cap['importance']:.2f}",
                    trigger_source="auto_promote",
                )
                if result["changed"]:
                    promoted_count += 1
            except Exception:
                continue
        
        if promoted_count > 0:
            summary["promoted"].append({"from": from_tier, "to": to_tier, "count": promoted_count})
            summary["total"] += promoted_count
    
    return summary


def demote_stale_capsules():
    """Auto-demote stale capsules based on rules (called by scheduler)."""
    summary = {"demoted": [], "total": 0}
    
    transitions = [
        ("medium_term", "short_term"),
        ("short_term", "working"),
    ]
    
    for from_tier, to_tier in transitions:
        candidates = get_capsules_eligible_for_demotion(from_tier, to_tier)
        demoted_count = 0
        
        for cap in candidates:
            try:
                result = tier_demote(
                    cap["capsule_id"],
                    to_tier=to_tier,
                    reason=f"auto: idle since {cap['updated_at']}",
                    trigger_source="auto_demote",
                )
                if result["changed"]:
                    demoted_count += 1
            except Exception:
                continue
        
        if demoted_count > 0:
            summary["demoted"].append({"from": from_tier, "to": to_tier, "count": demoted_count})
            summary["total"] += demoted_count
    
    return summary
