from backend.app.memory_runtime.sequence_mining import mine_tool_preferences
from backend.app.memory_runtime.policy_gate import evaluate_preference_candidate

def _events(scene, tool, n):
    return [{"scene": scene, "tool": tool, "ts": f"2026-01-01T00:00:{i:02d}"} for i in range(n)]

def test_recall_and_low_frequency_filter():
    rows = mine_tool_preferences(_events("build", "compiler", 6) + _events("build", "search", 2), window=20, min_support=5)
    assert rows and rows[0]["object"] == "compiler"

def test_threshold_and_support_boundaries():
    assert mine_tool_preferences(_events("x", "a", 4), min_support=5) == []
    assert mine_tool_preferences(_events("x", "a", 6) + _events("x", "b", 4), threshold=.7, min_support=5) == []
    assert mine_tool_preferences(_events("x", "a", 6) + _events("x", "b", 4), threshold=.55, min_support=5)

def test_dedup_and_reinforcement_confidence_monotonic():
    one = mine_tool_preferences(_events("x", "a", 5), min_support=1)[0]
    two = mine_tool_preferences(_events("x", "a", 10), min_support=1)[0]
    assert two["support"] > one["support"] and two["confidence"] >= one["confidence"]

def test_sequence_source_always_requires_confirmation():
    result = evaluate_preference_candidate({"subject": "x", "predicate": "prefers_tool", "object": "a", "source": "sequence_mining"})
    assert result["requires_confirmation"] is True

def test_empty_and_unsorted_timestamps_tolerated():
    assert mine_tool_preferences([]) == []
    assert len(mine_tool_preferences([{"scene": "x", "tool": "a", "ts": "bad"}] * 5, min_support=5)) == 1
