import uuid
from typing import Any
from ..db import get_conn, transaction
from ..audit.service import record
from .capsule_store import get_capsule, update_capsule, write_capsule, dumps, now


def reinforce(capsule_id: str, amount: float = 0.1) -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]
    st["lifecycle"] = "reinforced" if st.get("lifecycle") == "active" else st.get("lifecycle", "candidate")
    st["importance_score"] = min(1.0, float(st.get("importance_score", 0.5)) + amount)
    st["retention_score"] = min(1.0, float(st.get("retention_score", 0.5)) + amount)
    return update_capsule(capsule_id, state=st)


def deprecate(capsule_id: str, reason: str = "misleading") -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]; st["lifecycle"] = "deprecated"; st["deprecation_reason"] = reason
    return update_capsule(capsule_id, state=st)


def conflict_mark(capsule_id: str, reason: str = "conflict") -> dict[str, Any]:
    cap = get_capsule(capsule_id)
    if not cap:
        raise ValueError(f"Capsule not found: {capsule_id}")
    st = cap["state"]; st["lifecycle"] = "conflicted"; st["conflict_reason"] = reason
    return update_capsule(capsule_id, state=st)


def supersede(old_capsule_id: str, *, new_content: dict[str, Any], memory_class: str = "knowledge") -> dict[str, Any]:
    old = get_capsule(old_capsule_id)
    if not old:
        raise ValueError(f"Capsule not found: {old_capsule_id}")
    new = write_capsule(memory_class=memory_class, content=new_content, source_type="eval", write_intent="explicit")
    old_state = old["state"]; old_state["lifecycle"] = "deprecated"; old_state.setdefault("superseded_by", []).append(new["capsule_id"])
    update_capsule(old_capsule_id, state=old_state)
    new_cap = get_capsule(new["capsule_id"])
    if not new_cap:
        raise ValueError(f"Newly created capsule not found: {new['capsule_id']}")
    st = new_cap["state"]; st.setdefault("supersedes", []).append(old_capsule_id)
    return update_capsule(new["capsule_id"], state=st)


def reflect_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actions = []
    
    # 04-#03: Batch-fetch all candidate capsules to avoid N+1 queries.
    # Before: helpful_memories=[A,B,C] → 3 get_capsule calls + 3 reinforce calls
    # (each reinforce internally calls get_capsule again) = 6 queries.
    # After: 1 batch fetch, operate on in-memory dict.
    helpful_ids = payload.get("helpful_memories", [])
    misleading_ids = payload.get("misleading_memories", [])
    all_ids = helpful_ids + misleading_ids
    
    if all_ids:
        from .capsule_store import get_capsules_batch
        caps_by_id = get_capsules_batch(all_ids)
        
        for cid in helpful_ids:
            if cid in caps_by_id:
                reinforce(cid)
                actions.append({"action": "reinforce", "capsule_id": cid})
        
        for cid in misleading_ids:
            if cid in caps_by_id:
                deprecate(cid)
                actions.append({"action": "deprecate", "capsule_id": cid})
    
    for risk in payload.get("new_risks", []):
        res = write_capsule(memory_class="risk", content=risk, source_type="eval", scene="coding", task_type="reflection", risk_class="medium")
        actions.append({"action": "promote", "capsule_id": res["capsule_id"], "memory_class": "risk"})
    reflection_id = "refl_" + uuid.uuid4().hex[:12]
    full = {**payload, "evolution_actions": actions}
    with transaction() as conn:
        conn.execute("INSERT INTO memory_reflections VALUES (?,?,?,?)", (reflection_id, task_id, dumps(full), now()))
    audit_id = record("task_reflection", {"reflection_id": reflection_id, "task_id": task_id, "actions": actions})
    return {"reflection_id": reflection_id, "task_id": task_id, "evolution_actions": actions, "audit_id": audit_id}
