"""Persistent cross-run item deduplication for scheduled pipelines."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit


_TRACKING_PARAMETERS = {
    "_ga",
    "dclid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "twclid",
}
_X_STATUS_PATH = re.compile(r"^/[^/]+/status/(\d+)(?:/|$)", re.IGNORECASE)


def item_identity(item: Any) -> str:
    """Return a stable identity for the same item across separate runs."""
    raw_url = str(getattr(item, "url", "") or "").strip()
    if raw_url:
        try:
            parsed = urlsplit(raw_url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            path = parsed.path.rstrip("/") or "/"
            if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
                match = _X_STATUS_PATH.match(path)
                if match:
                    return f"x-status:{match.group(1)}"

            query = sorted(
                (name, value)
                for name, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not name.lower().startswith("utm_")
                and name.lower() not in _TRACKING_PARAMETERS
            )
            if host:
                return f"url:{host}{path}?{urlencode(query)}" if query else f"url:{host}{path}"
        except ValueError:
            pass

    item_id = str(getattr(item, "id", "") or "").strip()
    if item_id:
        return f"id:{item_id}"
    raise ValueError("content item must have a URL or ID for cross-run deduplication")


@dataclass
class SeenFilterResult:
    """New items claimed by a run and duplicate diagnostics."""

    items: list[Any]
    duplicate_count: int


@dataclass
class SeenItemStore:
    """SQLite-backed claims that prevent repeated processing across runs."""

    path: Path
    retention_days: int = 30
    stale_claim_hours: int = 6

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_items (
                    item_key TEXT PRIMARY KEY,
                    first_pool TEXT NOT NULL,
                    last_pool TEXT NOT NULL,
                    first_run_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    committed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS seen_items_last_seen_idx "
                "ON seen_items(last_seen_at)"
            )

    def claim_new(self, pool: str, run_id: str, items: Iterable[Any]) -> SeenFilterResult:
        """Atomically claim unseen items for one run."""
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        retention_cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        stale_cutoff = (now - timedelta(hours=self.stale_claim_hours)).isoformat()
        new_items: list[Any] = []
        duplicate_count = 0
        claimed_in_batch: set[str] = set()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM seen_items WHERE committed = 1 AND last_seen_at < ?",
                (retention_cutoff,),
            )
            connection.execute(
                "DELETE FROM seen_items WHERE committed = 0 AND first_seen_at < ?",
                (stale_cutoff,),
            )

            for item in items:
                key = item_identity(item)
                if key in claimed_in_batch:
                    duplicate_count += 1
                    continue
                claimed_in_batch.add(key)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO seen_items (
                        item_key, first_pool, last_pool, first_run_id,
                        first_seen_at, last_seen_at, committed
                    ) VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (key, pool, pool, run_id, now_text, now_text),
                )
                if cursor.rowcount == 1:
                    new_items.append(item)
                    continue

                duplicate_count += 1
                connection.execute(
                    "UPDATE seen_items SET last_pool = ?, last_seen_at = ? WHERE item_key = ?",
                    (pool, now_text, key),
                )

        return SeenFilterResult(items=new_items, duplicate_count=duplicate_count)

    def cleanup(self) -> int:
        """Delete committed records past retention and abandoned claims."""
        now = datetime.now(timezone.utc)
        retention_cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        stale_cutoff = (now - timedelta(hours=self.stale_claim_hours)).isoformat()
        with self._connect() as connection:
            committed = connection.execute(
                "DELETE FROM seen_items WHERE committed = 1 AND last_seen_at < ?",
                (retention_cutoff,),
            ).rowcount
            abandoned = connection.execute(
                "DELETE FROM seen_items WHERE committed = 0 AND first_seen_at < ?",
                (stale_cutoff,),
            ).rowcount
        return committed + abandoned

    def commit_run(self, run_id: str) -> None:
        """Confirm claims after the run's raw artifact has been saved."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE seen_items SET committed = 1 WHERE first_run_id = ? AND committed = 0",
                (run_id,),
            )

    def release_run(self, run_id: str) -> None:
        """Release uncommitted claims when raw artifact persistence fails."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM seen_items WHERE first_run_id = ? AND committed = 0",
                (run_id,),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
