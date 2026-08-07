"""Tests for memory tier management (issue #56)."""
import pytest
from backend.app.memory_runtime.tier_manager import (
    migrate_tier_column,
    tier_promote,
    tier_demote,
)
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.db import get_conn


def test_migrate_tier_column():
    """Test tier column migration is idempotent."""
    # Migration may have already run via init_db.main(), so we just verify
    # (a) it's idempotent (doesn't raise on repeated calls)
    # (b) 'tier' column exists after calling it
    result1 = migrate_tier_column()
    # Result can be True (applied now) or False (already applied)
    assert result1 in (True, False), "migrate_tier_column() should return bool"
    
    # Second run should be no-op
    result2 = migrate_tier_column()
    assert result2 is False, "Second migration should return False (already applied)"
    
    # Verify 'tier' column exists
    with get_conn() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_capsules_v2)")}
        assert "tier" in columns, "'tier' column should exist after migration"


def test_tier_promote():
    """Test tier_promote() can promote a capsule to a higher tier."""
    # Create a test capsule
    capsule = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": "test tier promote"},
        source_type="user_input",
    )
    capsule_id = capsule["capsule_id"]
    
    # Verify initial tier is 'working' (migration default)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "working", "New capsule should default to 'working' tier"
    
    # Promote to short_term
    result = tier_promote(capsule_id, to_tier="short_term", reason="test promotion")
    assert result["changed"] is True
    assert result["from_tier"] == "working"
    assert result["to_tier"] == "short_term"
    assert result["reason"] == "test promotion"
    
    # Verify tier was updated
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        assert row[0] == "short_term"
    
    # Promote again to same tier should be no-op
    result2 = tier_promote(capsule_id, to_tier="short_term", reason="redundant")
    assert result2["changed"] is False
    assert result2["reason"] == "already_at_target_tier"


def test_tier_demote():
    """Test tier_demote() can demote a capsule to a lower tier."""
    # Create a test capsule and promote it to medium_term
    capsule = write_capsule(
        memory_class="knowledge",
        content={"kind": "fact", "statement": "test tier demote"},
        source_type="user_input",
    )
    capsule_id = capsule["capsule_id"]
    
    # Promote to medium_term first
    tier_promote(capsule_id, to_tier="medium_term", reason="setup for demote test")
    
    # Demote to short_term
    result = tier_demote(capsule_id, to_tier="short_term", reason="test demotion")
    assert result["changed"] is True
    assert result["from_tier"] == "medium_term"
    assert result["to_tier"] == "short_term"
    
    # Verify tier was updated
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tier FROM memory_capsules_v2 WHERE capsule_id=?",
            (capsule_id,),
        ).fetchone()
        assert row[0] == "short_term"


def test_tier_promote_invalid_tier():
    """Test tier_promote() rejects invalid tier names."""
    capsule = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": "test invalid tier"},
        source_type="user_input",
    )
    capsule_id = capsule["capsule_id"]
    
    with pytest.raises(ValueError, match="Invalid to_tier"):
        tier_promote(capsule_id, to_tier="超长期", reason="invalid")


def test_tier_promote_nonexistent_capsule():
    """Test tier_promote() raises ValueError for nonexistent capsule."""
    with pytest.raises(ValueError, match="Capsule .* not found"):
        tier_promote("cap_nonexistent_id", to_tier="short_term", reason="test")
