from __future__ import annotations

import asyncio

import pytest

from src import n8n_api


class FakeRunStore:
    def __init__(self, stages: set[str] | None = None):
        self.stages = stages or set()

    def has_stage(self, run_id: str, stage: str) -> bool:
        return stage in self.stages


class FakeService:
    def __init__(self, *, raw_count: int = 1, filtered_count: int = 1):
        self.run_store = FakeRunStore({"raw", "scored", "filtered", "enriched"})
        self.raw_count = raw_count
        self.filtered_count = filtered_count
        self.calls: list[tuple[str, dict]] = []

    async def fetch_items(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        return {"run_id": "run-1", "fetched": self.raw_count}

    async def score_items(self, **kwargs):
        self.calls.append(("score", kwargs))
        return {"run_id": kwargs["run_id"], "scored": self.raw_count}

    async def filter_items(self, **kwargs):
        self.calls.append(("filter", kwargs))
        return {"run_id": kwargs["run_id"], "kept": self.filtered_count}

    async def enrich_items(self, **kwargs):
        self.calls.append(("enrich", kwargs))
        return {"run_id": kwargs["run_id"], "status": "success", "enriched": 1}

    def get_run_stage(self, *, run_id: str, stage: str, max_items: int):
        count = self.raw_count if stage == "raw" else self.filtered_count
        items = [{"id": "item-1"}] if count else []
        return {"run_id": run_id, "stage": stage, "count": count, "items": items}

    def get_run_meta(self, run_id: str):
        return {
            "run_id": run_id,
            "meta": {
                "raw_count": self.raw_count,
                "raw_count_before_merge": self.raw_count,
                "scored_count": self.raw_count,
                "selected_count": self.filtered_count,
                "filtered_count": self.filtered_count,
                "enrichment_status": "success",
                "enriched_count": self.filtered_count,
                "enrichment_failed_count": 0,
            },
        }


def test_fetch_stage_creates_run(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    result = asyncio.run(n8n_api._fetch_stage({"hours": 36, "cadence": "daily"}))

    assert result["run_id"] == "run-1"
    assert result["stage"] == "raw"
    assert service.calls == [
        (
            "fetch",
            {"hours": 36, "cadence": "daily", "content_topics": True},
        )
    ]


def test_fetch_stage_forwards_explicit_seen_dedup_override(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    asyncio.run(
        n8n_api._fetch_stage(
            {"hours": 24, "cadence": "reserve", "deduplicate_seen": True}
        )
    )

    assert service.calls == [
        (
            "fetch",
            {
                "hours": 24,
                "cadence": "reserve",
                "content_topics": True,
                "deduplicate_seen": True,
            },
        )
    ]


def test_fetch_stage_routes_shared_sources_by_content(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    result = asyncio.run(n8n_api._fetch_stage({"cadence": "daily"}))

    assert result["run_id"] == "run-1"
    assert service.calls == [
        (
            "fetch",
            {"hours": 24, "cadence": "daily", "content_topics": True},
        )
    ]


def test_fetch_stage_uses_cadence_default_windows(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    asyncio.run(n8n_api._fetch_stage({"cadence": "daily"}))
    asyncio.run(n8n_api._fetch_stage({"cadence": "weekly"}))
    asyncio.run(n8n_api._fetch_stage({"cadence": "reserve"}))

    assert service.calls == [
        ("fetch", {"hours": 24, "cadence": "daily", "content_topics": True}),
        ("fetch", {"hours": 168, "cadence": "weekly", "content_topics": True}),
        ("fetch", {"hours": 720, "cadence": "reserve", "content_topics": True}),
    ]


@pytest.mark.parametrize("removed_option", ["topic_id", "pool", "content_topics"])
def test_fetch_stage_rejects_removed_routing_options(removed_option):
    with pytest.raises(ValueError, match="unsupported fetch options"):
        asyncio.run(n8n_api._fetch_stage({removed_option: "legacy"}))


def test_empty_run_skips_remaining_stages(monkeypatch):
    service = FakeService(raw_count=0, filtered_count=0)
    service.run_store.stages = {"raw"}
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    scored = asyncio.run(n8n_api._score_stage({"run_id": "run-1"}))
    filtered = asyncio.run(n8n_api._filter_stage({"run_id": "run-1"}))
    enriched = asyncio.run(n8n_api._enrich_stage({"run_id": "run-1"}))

    assert scored["skipped"] is True
    assert filtered["skipped"] is True
    assert enriched["skipped"] is True
    assert enriched["items"] == []
    assert service.calls == []


def test_filter_and_enrich_return_stage_results(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    filtered = asyncio.run(
        n8n_api._filter_stage({"run_id": "run-1", "threshold": 7, "topic_dedup": False})
    )
    enriched = asyncio.run(n8n_api._enrich_stage({"run_id": "run-1"}))

    assert filtered["stage"] == "filtered"
    assert enriched["stage"] == "enriched"
    assert enriched["items"] == [{"id": "item-1"}]
    assert enriched["stats"]["fetch"]["fetched"] == 1
    assert enriched["stats"]["filter"]["kept"] == 1
    assert (
        "filter",
        {"run_id": "run-1", "threshold": 7.0, "topic_dedup": False},
    ) in service.calls
    assert ("enrich", {"run_id": "run-1"}) in service.calls


def test_stage_routes_and_validation():
    assert set(n8n_api._POST_ROUTES) == {
        "/fetch",
        "/score",
        "/filter",
        "/enrich",
        "/report",
    }
    with pytest.raises(ValueError, match="run_id"):
        n8n_api._require_run_id({})
    with pytest.raises(ValueError, match="threshold"):
        n8n_api._parse_threshold({"threshold": 11})
    with pytest.raises(ValueError, match="cadence"):
        n8n_api._parse_cadence({"cadence": "everything"})


def test_report_stage_uses_enriched_items(monkeypatch):
    service = FakeService()
    captured = {}

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {"markdown": "/output/report.md", "cards": ["/output/card.png"]}

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "generate_xiaohongshu_report", fake_report)

    result = asyncio.run(n8n_api._report_stage({"run_id": "run-1", "max_cards": 10}))

    assert result["stage"] == "report"
    assert result["report"]["cards"] == ["/output/card.png"]
    assert captured["run_id"] == "run-1"
    assert captured["items"] == [{"id": "item-1"}]
    assert captured["max_cards"] == 10


def test_report_stage_generates_an_empty_report(monkeypatch):
    service = FakeService(raw_count=0, filtered_count=0)
    service.run_store.stages = {"raw"}
    captured = {}

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {"markdown": "/output/report.md", "cards": []}

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "generate_xiaohongshu_report", fake_report)

    result = asyncio.run(n8n_api._report_stage({"run_id": "run-1"}))

    assert result["stage"] == "report"
    assert captured["items"] == []
