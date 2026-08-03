from datetime import datetime, timedelta, timezone
import os

from src.mcp.retention import cleanup_report_output


def test_report_cleanup_is_age_and_name_scoped(tmp_path) -> None:
    old_report = tmp_path / "game-inspiration-radar-2026-06-01-run-old"
    old_report.mkdir()
    (old_report / "report.md").write_text("old", encoding="utf-8")
    recent_report = tmp_path / "game-tech-daily-2026-08-01.md"
    recent_report.write_text("recent", encoding="utf-8")
    unrelated = tmp_path / "user-file.txt"
    unrelated.write_text("keep", encoding="utf-8")
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    old_time = (now - timedelta(days=31)).timestamp()
    recent_time = (now - timedelta(days=1)).timestamp()
    os.utime(old_report, (old_time, old_time))
    os.utime(recent_report, (recent_time, recent_time))
    os.utime(unrelated, (old_time, old_time))

    removed = cleanup_report_output(tmp_path, 30, now=now)

    assert removed == 1
    assert not old_report.exists()
    assert recent_report.exists()
    assert unrelated.exists()
