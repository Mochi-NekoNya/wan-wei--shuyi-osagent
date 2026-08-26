"""Integration test for tier management API routes."""
from backend.app.memory_runtime.capsule_store import write_capsule
from backend.app.memory_runtime.tier_manager import tier_promote
from backend.app.app_runtime import app
from fastapi.testclient import TestClient


client = TestClient(app)


def test_memory_tiers_endpoint():
    """Test GET /reproduction/memory-tiers returns tier distribution."""
    response = client.get("/reproduction/memory-tiers")
    assert response.status_code == 200
    data = response.json()
    assert "tiers" in data
    assert "tier_order" in data
    assert "total_capsules" in data
    assert data["tier_order"] == ["working", "short_term", "medium_term", "long_term"]


def test_tier_promote_api():
    """Test POST /memory/tier/promote promotes a capsule."""
    # Create a test capsule
    capsule = write_capsule(
        memory_class="episodic",
        content={"kind": "memory_note", "summary": "test tier API promote"},
        source_type="user_input",
    )
    capsule_id = capsule["capsule_id"]
    
    # Promote via API
    response = client.post(
        "/memory/tier/promote",
        params={"capsule_id": capsule_id, "to_tier": "short_term", "reason": "test_api"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["changed"] is True
    assert data["from_tier"] == "working"
    assert data["to_tier"] == "short_term"


def test_tier_demote_api():
    """Test POST /memory/tier/demote demotes a capsule."""
    # Create and promote a capsule first
    capsule = write_capsule(
        memory_class="knowledge",
        content={"kind": "fact", "statement": "test tier API demote"},
        source_type="user_input",
    )
    capsule_id = capsule["capsule_id"]
    tier_promote(capsule_id, to_tier="medium_term", reason="setup")
    
    # Demote via API
    response = client.post(
        "/memory/tier/demote",
        params={"capsule_id": capsule_id, "to_tier": "short_term", "reason": "test_api"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["changed"] is True
    assert data["from_tier"] == "medium_term"
    assert data["to_tier"] == "short_term"


def test_auto_promote_api():
    """Test POST /memory/tier/auto-promote runs auto-promotion."""
    response = client.post("/memory/tier/auto-promote")
    assert response.status_code == 200
    data = response.json()
    assert "promoted" in data
    assert "total" in data
    # May be 0 if no capsules meet criteria (which is fine for test)
    assert isinstance(data["total"], int)


def test_auto_demote_api():
    """Test POST /memory/tier/auto-demote runs auto-demotion."""
    response = client.post("/memory/tier/auto-demote")
    assert response.status_code == 200
    data = response.json()
    assert "demoted" in data
    assert "total" in data
    assert isinstance(data["total"], int)
