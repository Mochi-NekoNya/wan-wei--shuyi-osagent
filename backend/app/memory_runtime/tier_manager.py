"""Memory tier management: promotion/demotion logic for short/mid/long-term memory.

对应 GitHub issue #56: 短期/中期记忆自动流转机制
赛题要求(6): 兼容与记忆模块中短期、中期记忆间的数据流转
"""
from datetime import datetime, timedelta
from typing import Any

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
