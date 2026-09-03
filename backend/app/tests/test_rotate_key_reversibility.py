import pytest

from backend.app.security.auth import (
    _api_key_hash,
    _verify_api_key,
    actor_id_from_api_key,
    rotate_api_key,
)


def test_rotate_round_trip_reactivates_original_key(isolated_db):
    identity = actor_id_from_api_key("key-a")
    assert rotate_api_key("key-a", "key-b") == identity
    assert not _verify_api_key("key-a")
    assert rotate_api_key("key-b", "key-a") == identity
    assert _verify_api_key("key-a")
    assert not _verify_api_key("key-b")


def test_rotate_multiple_round_trips_are_repeatable(isolated_db):
    identity = actor_id_from_api_key("key-a")
    for old_key, new_key in (("key-a", "key-b"), ("key-b", "key-a"), ("key-a", "key-b"), ("key-b", "key-a")):
        assert rotate_api_key(old_key, new_key) == identity
    assert _verify_api_key("key-a")
    assert not _verify_api_key("key-b")


def test_rotate_old_key_is_immediately_rejected(isolated_db):
    actor_id_from_api_key("old-key")
    rotate_api_key("old-key", "new-key")
    assert not _verify_api_key("old-key")
    assert _verify_api_key("new-key")


def test_rotate_failure_rolls_back_prior_update(isolated_db):
    actor_id_from_api_key("key-a")
    with pytest.raises(Exception):
        rotate_api_key("key-a", "key-a")
    assert _verify_api_key("key-a")
    from backend.app.db import get_conn
    row = get_conn().execute(
        "SELECT is_active FROM identity WHERE api_key_hash=?", (_api_key_hash("key-a"),)
    ).fetchone()
    assert row["is_active"] == 1
