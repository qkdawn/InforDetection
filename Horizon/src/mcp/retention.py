"""Retention cleanup for generated Horizon report artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPORT_PREFIXES = (
    "game-inspiration-radar-",
    "game-tech-daily-",
)


def cleanup_report_output(
    root: Path, retention_days: int, now: datetime | None = None
) -> int:
    """Delete expired Horizon-owned report files and directories."""
    root = Path(root)
    if not root.exists():
        return 0
    resolved_root = root.resolve()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    removed = 0
    for entry in root.iterdir():
        if not entry.name.startswith(REPORT_PREFIXES):
            continue
        modified = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            continue
        target = entry.resolve()
        if target.parent != resolved_root:
            raise ValueError(f"Refusing to delete report outside output root: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed += 1
    return removed
