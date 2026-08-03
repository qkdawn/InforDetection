from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.mcp.service import HorizonPipelineService
from src.models import ContentItem, SourceType


def _item() -> ContentItem:
    return ContentItem(
        id="feed-item-1",
        source_type=SourceType.RSS,
        title="Repeated item",
        url="https://x.com/example/status/123456",
        content="content",
        author="tester",
        published_at=datetime.now(timezone.utc),
        profile="tech-news",
    )


def _service(tmp_path: Path, monkeypatch) -> HorizonPipelineService:
    service = HorizonPipelineService(runs_root=tmp_path / "mcp-runs")
    config = SimpleNamespace(
        collection=SimpleNamespace(
            default_source_pool="daily",
            cross_run_dedup_enabled=True,
            retention_days=30,
        ),
        sources=SimpleNamespace(rss=[]),
    )
    monkeypatch.setattr(service, "_profiles", lambda ctx: object())
    monkeypatch.setattr(
        service,
        "_build_context",
        lambda **kwargs: (
            SimpleNamespace(
                horizon_path=tmp_path,
                config_path=tmp_path / "config.json",
                runtime=SimpleNamespace(),
                config=config,
            ),
            ["rss"],
            [],
        ),
    )
    monkeypatch.setattr(
        "src.mcp.service.make_storage", lambda runtime, config_path: object()
    )

    class FakeOrchestrator:
        async def fetch_all_sources(self, since, source_pool=None):
            return [_item()]

        def merge_cross_source_duplicates(self, items):
            return items

    monkeypatch.setattr(
        "src.mcp.service.make_orchestrator",
        lambda runtime, config, storage, console, profiles: FakeOrchestrator(),
    )
    return service


def test_automatic_pool_drops_item_seen_in_previous_run(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)

    first = asyncio.run(service.fetch_items(hours=24, pool="x_watch"))
    second = asyncio.run(service.fetch_items(hours=24, pool="x_watch"))

    assert first["fetched"] == 1
    assert first["seen_duplicates_removed"] == 0
    assert second["fetched"] == 0
    assert second["seen_duplicates_removed"] == 1
    assert second["cross_run_dedup_enabled"] is True
    assert second["retention_days"] == 30
    assert second["retention_cleanup"] == {
        "seen_records": 0,
        "runs": 0,
        "reports": 0,
    }
    assert service.run_store.load_items(second["run_id"], "raw") == []


def test_reserve_pool_allows_reprocessing_by_default(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)

    first = asyncio.run(service.fetch_items(hours=24, pool="reserve"))
    second = asyncio.run(service.fetch_items(hours=24, pool="reserve"))

    assert first["fetched"] == 1
    assert second["fetched"] == 1
    assert first["cross_run_dedup_enabled"] is False
    assert second["seen_duplicates_removed"] == 0


def test_reserve_pool_can_opt_into_cross_run_dedup(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)

    asyncio.run(
        service.fetch_items(hours=24, pool="reserve", deduplicate_seen=True)
    )
    second = asyncio.run(
        service.fetch_items(hours=24, pool="reserve", deduplicate_seen=True)
    )

    assert second["fetched"] == 0
    assert second["seen_duplicates_removed"] == 1
