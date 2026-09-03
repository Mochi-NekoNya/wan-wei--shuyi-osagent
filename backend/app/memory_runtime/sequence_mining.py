"""Pure sequence-based tool preference mining."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Iterable

DEFAULT_WINDOW = 20
DEFAULT_MIN_SUPPORT = 5
DEFAULT_THRESHOLD = 0.6

def _time_key(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min

def mine_tool_preferences(sequences: Iterable[dict[str, Any]], *, window: int = DEFAULT_WINDOW,
                          min_support: int = DEFAULT_MIN_SUPPORT,
                          threshold: float = DEFAULT_THRESHOLD) -> list[dict[str, Any]]:
    if window <= 0 or min_support <= 0 or not 0 <= threshold <= 1:
        return []
    events = [e for e in sequences if isinstance(e, dict) and e.get("scene") and e.get("tool")]
    events.sort(key=lambda e: _time_key(e.get("ts")))
    scene_counts: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for event in events[-window:]:
        scene, tool = str(event["scene"]), str(event["tool"])
        scene_counts[scene] = scene_counts.get(scene, 0) + 1
        pair = (scene, tool)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    result = []
    for (scene, tool), support in pair_counts.items():
        confidence = (support + 1) / (scene_counts[scene] + 2)
        if support >= min_support and confidence >= threshold:
            result.append({"subject": scene, "predicate": "prefers_tool", "object": tool,
                           "confidence": confidence, "support": support, "source": "sequence_mining"})
    return result

__all__ = ["mine_tool_preferences", "DEFAULT_WINDOW", "DEFAULT_MIN_SUPPORT", "DEFAULT_THRESHOLD"]
