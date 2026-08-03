import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.mcp.seen_store import SeenItemStore, item_identity


def _item(item_id: str, url: str):
    return SimpleNamespace(id=item_id, url=url)


def test_x_status_identity_ignores_domain_and_account_name() -> None:
    first = _item("one", "https://x.com/example/status/123456?utm_source=test")
    second = _item("two", "https://twitter.com/renamed/status/123456")

    assert item_identity(first) == "x-status:123456"
    assert item_identity(second) == "x-status:123456"


def test_normal_url_identity_removes_tracking_and_sorts_query() -> None:
    first = _item("one", "https://Example.com/post/?b=2&utm_source=x&a=1")
    second = _item("two", "http://example.com/post?a=1&b=2")

    assert item_identity(first) == item_identity(second)


def test_committed_item_is_removed_from_later_run(tmp_path) -> None:
    store = SeenItemStore(tmp_path / "seen.sqlite3")
    item = _item("one", "https://x.com/example/status/123")

    first = store.claim_new("x_watch", "run-1", [item])
    store.commit_run("run-1")
    second = store.claim_new("x_watch", "run-2", [item])

    assert first.items == [item]
    assert first.duplicate_count == 0
    assert second.items == []
    assert second.duplicate_count == 1


def test_release_allows_item_to_be_retried(tmp_path) -> None:
    store = SeenItemStore(tmp_path / "seen.sqlite3")
    item = _item("one", "https://example.com/retry")

    store.claim_new("daily", "run-failed", [item])
    store.release_run("run-failed")
    retried = store.claim_new("daily", "run-retry", [item])

    assert retried.items == [item]
    assert retried.duplicate_count == 0


def test_duplicate_inside_same_batch_is_removed(tmp_path) -> None:
    store = SeenItemStore(tmp_path / "seen.sqlite3")
    first = _item("one", "https://example.com/same")
    second = _item("two", "https://example.com/same?utm_campaign=test")

    result = store.claim_new("daily", "run-1", [first, second])

    assert result.items == [first]
    assert result.duplicate_count == 1


def test_cleanup_removes_committed_records_older_than_retention(tmp_path) -> None:
    database = tmp_path / "seen.sqlite3"
    store = SeenItemStore(database, retention_days=30)
    item = _item("one", "https://x.com/example/status/456")
    store.claim_new("x_watch", "run-old", [item])
    store.commit_run("run-old")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE seen_items SET last_seen_at = ? WHERE first_run_id = ?",
            (old_timestamp, "run-old"),
        )

    assert store.cleanup() == 1
    assert store.claim_new("x_watch", "run-new", [item]).items == [item]
