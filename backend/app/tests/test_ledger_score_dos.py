"""Regression coverage for the TEXT ledger-id recursion DoS (issue #173)."""

import time

from backend.app.db import get_conn
from backend.app.security.score import _check_audit_ledger_intact, compute_security_score


def _insert_ledger(ledger_id: str | None) -> None:
    get_conn().execute(
        """INSERT INTO memory_ledger
           (ledger_id, op_type, capsule_id, actor, risk_class, created_at)
           VALUES (?, 'write', 'cap_test', 'test', 'low', '2026-01-01T00:00:00Z')""",
        (ledger_id,),
    )
    get_conn().commit()


def test_compute_security_score_real_text_schema_is_fast(isolated_db):
    for index in range(400):
        _insert_ledger(f"led_{index:012x}")
    started = time.perf_counter()
    result = compute_security_score()
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    check = next(item for item in result["checks"] if item["id"] == "audit_ledger_intact")
    assert check["passed"]


def test_non_contiguous_random_ids_pass_but_malformed_id_fails(isolated_db):
    _insert_ledger("led_deadbeef0001")
    _insert_ledger("led_00000000000f")
    assert _check_audit_ledger_intact()["passed"]

    _insert_ledger("missing_prefix")
    result = _check_audit_ledger_intact()
    assert not result["passed"]
    assert "格式缺陷" in result["detail"]


def test_empty_and_single_row_boundaries(isolated_db):
    assert _check_audit_ledger_intact()["passed"]
    _insert_ledger("led_000000000001")
    assert _check_audit_ledger_intact()["passed"]


def test_null_ledger_id_is_malformed(isolated_db):
    _insert_ledger(None)
    result = _check_audit_ledger_intact()
    assert not result["passed"]
    assert "格式缺陷" in result["detail"]
