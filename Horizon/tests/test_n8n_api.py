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

    def replay_item(self, **kwargs):
        self.calls.append(("replay", kwargs))
        return {
            "run_id": "run-replay",
            "source_run_id": kwargs["source_run_id"],
            "fetched": 1,
            "item": {
                "id": "item-1",
                "title": "Replayed item",
                "url": kwargs["item_url"],
                "source_type": "rss",
                "published_at": "2026-08-08T00:00:00Z",
            },
        }

    async def score_items(self, **kwargs):
        self.calls.append(("score", kwargs))
        return {"run_id": kwargs["run_id"], "scored": self.raw_count}

    async def filter_items(self, **kwargs):
        self.calls.append(("filter", kwargs))
        return {"run_id": kwargs["run_id"], "kept": self.filtered_count}

    async def enrich_items(self, **kwargs):
        self.calls.append(("enrich", kwargs))
        return {"run_id": kwargs["run_id"], "status": "success", "enriched": 1}

    async def evaluate_items(self, **kwargs):
        self.calls.append(("evaluate", kwargs))
        return {"run_id": kwargs["run_id"], "status": "success", "evaluated": 1}

    async def select_items(self, **kwargs):
        self.calls.append(("select", kwargs))
        return {"run_id": kwargs["run_id"], "selected": 1}

    def get_run_stage(self, *, run_id: str, stage: str, max_items: int):
        count = self.raw_count if stage == "raw" else self.filtered_count
        items = [{"id": f"item-{index + 1}"} for index in range(count)]
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


def test_replay_stage_creates_single_item_raw_run(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    result = asyncio.run(
        n8n_api._replay_stage(
            {
                "source_run_id": "run-source",
                "item_url": "https://example.com/item-1",
            }
        )
    )

    assert result["run_id"] == "run-replay"
    assert result["stage"] == "raw"
    assert result["item"]["title"] == "Replayed item"
    assert service.calls == [
        (
            "replay",
            {
                "source_run_id": "run-source",
                "item_url": "https://example.com/item-1",
            },
        )
    ]


@pytest.mark.parametrize("missing", ["source_run_id", "item_url"])
def test_replay_stage_requires_source_run_and_url(missing):
    options = {
        "source_run_id": "run-source",
        "item_url": "https://example.com/item-1",
    }
    options.pop(missing)

    with pytest.raises(ValueError, match=missing):
        asyncio.run(n8n_api._replay_stage(options))


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
        {
            "run_id": "run-1",
            "threshold": 7.0,
            "topic_dedup": False,
            "apply_balance": False,
        },
    ) in service.calls
    assert ("enrich", {"run_id": "run-1"}) in service.calls


def test_stage_routes_and_validation():
    assert set(n8n_api._POST_ROUTES) == {
        "/fetch",
        "/replay",
        "/score",
        "/filter",
        "/research",
        "/evaluate",
        "/select",
        "/enrich",
        "/report",
        "/feishu",
        "/psychology-brief",
        "/psychology/topic",
        "/psychology/angles",
        "/psychology/insight",
        "/psychology/script",
        "/psychology/review",
        "/psychology/render",
    }
    with pytest.raises(ValueError, match="run_id"):
        n8n_api._require_run_id({})
    with pytest.raises(ValueError, match="threshold"):
        n8n_api._parse_threshold({"threshold": 11})
    with pytest.raises(ValueError, match="cadence"):
        n8n_api._parse_cadence({"cadence": "everything"})


def test_evaluate_and_select_preserve_empty_pipeline(monkeypatch):
    service = FakeService(raw_count=1, filtered_count=0)
    service.run_store.stages = {"raw", "scored", "filtered", "researched"}
    saved: dict[str, list] = {}
    metadata: dict[str, object] = {}
    service.run_store.save_items = lambda run_id, stage, items: saved.setdefault(stage, items)  # type: ignore[attr-defined]
    service.run_store.update_meta = lambda run_id, updates: metadata.update(updates) or metadata  # type: ignore[attr-defined]
    service.run_store.write_json = lambda run_id, name, payload: payload  # type: ignore[attr-defined]
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    evaluated = asyncio.run(n8n_api._evaluate_stage({"run_id": "run-1"}))
    service.run_store.stages.add("evaluated")
    selected = asyncio.run(n8n_api._select_stage({"run_id": "run-1", "limit": 10}))

    assert evaluated["skipped"] is True
    assert selected["skipped"] is True
    assert saved == {"evaluated": [], "selected": []}
    assert metadata["selection_method"] == "empty"


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
    assert captured["max_cards"] == 2


def test_report_stage_refuses_nonempty_candidates_without_enrichment(monkeypatch):
    service = FakeService(raw_count=2, filtered_count=1)
    service.run_store.stages = {"raw", "scored", "filtered", "researched"}
    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)

    with pytest.raises(ValueError, match="no completed enriched stage"):
        asyncio.run(n8n_api._report_stage({"run_id": "run-1"}))


def test_report_stage_uses_empty_enriched_stage_after_all_rejections(monkeypatch):
    service = FakeService(raw_count=3, filtered_count=2)
    captured = {}

    def get_run_stage(*, run_id: str, stage: str, max_items: int):
        if stage == "enriched":
            return {"run_id": run_id, "stage": stage, "count": 0, "items": []}
        return FakeService.get_run_stage(
            service, run_id=run_id, stage=stage, max_items=max_items
        )

    service.get_run_stage = get_run_stage  # type: ignore[method-assign]

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {"markdown": "/output/report.md", "cards": []}

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "generate_xiaohongshu_report", fake_report)

    result = asyncio.run(n8n_api._report_stage({"run_id": "run-1"}))

    assert result["stage"] == "report"
    assert captured["items"] == []
    assert captured["max_cards"] == 2


def test_report_stage_defaults_to_one_card_per_item(monkeypatch):
    service = FakeService(filtered_count=19)
    captured = {}

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {"markdown": "/output/report.md", "cards": []}

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "generate_xiaohongshu_report", fake_report)

    result = asyncio.run(n8n_api._report_stage({"run_id": "run-1"}))

    assert result["stage"] == "report"
    assert len(captured["items"]) == 19
    assert captured["max_cards"] == 21


def test_report_stage_does_not_cap_default_image_cards(monkeypatch):
    service = FakeService(filtered_count=40)
    captured = {}

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {"markdown": "/output/report.md", "cards": []}

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "generate_xiaohongshu_report", fake_report)

    asyncio.run(n8n_api._report_stage({"run_id": "run-1"}))

    assert len(captured["items"]) == 40
    assert captured["max_cards"] == 42


def test_feishu_stage_delivers_matching_report(monkeypatch):
    captured = {}

    async def fake_deliver(report):
        captured.update(report)
        return {"card_count": 2}

    monkeypatch.setattr(n8n_api, "deliver_report_to_feishu", fake_deliver)
    report = {"run_id": "run-1", "markdown": "/output/report.md", "cards": []}

    result = asyncio.run(n8n_api._feishu_stage({"run_id": "run-1", "report": report}))

    assert result == {
        "ok": True,
        "run_id": "run-1",
        "stage": "feishu",
        "delivery": {"card_count": 2},
    }
    assert captured == report


def test_feishu_stage_rejects_mismatched_run_id():
    with pytest.raises(ValueError, match="must match"):
        asyncio.run(
            n8n_api._feishu_stage({"run_id": "run-1", "report": {"run_id": "run-2"}})
        )


def test_psychology_brief_stage_generates_report_without_delivery(monkeypatch):
    service = FakeService()
    service.run_store.create_run = lambda: "run-psych"
    service.run_store.update_meta = lambda run_id, updates: updates
    captured = {}

    class FakeGenerator:
        async def generate(self, topic, context):
            captured["topic"] = topic
            captured["context"] = context
            return {
                "angles": {"candidates": [{"label": "等待过期"}]},
                "insight": {"core_thesis": "拖着的不是字，是后续对话"},
                "script": {
                    "title": "你不是不想回",
                    "pages": [{"role": "cover"}, {"role": "turn"}, {"role": "aftertaste"}],
                },
                "review": {"verdict": "pass", "notes": ["通过"]},
            }

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": "run-psych",
            "markdown": "/output/report.md",
            "cards": ["/output/01.png"],
            "card_count": 1,
        }

    async def unexpected_delivery(report):
        raise AssertionError("delivery must be opt-in")

    monkeypatch.setattr(n8n_api, "HorizonPipelineService", lambda: service)
    monkeypatch.setattr(n8n_api, "create_psychology_generator", lambda: FakeGenerator())
    monkeypatch.setattr(n8n_api, "generate_psychology_report", fake_report)
    monkeypatch.setattr(n8n_api, "deliver_report_to_feishu", unexpected_delivery)

    result = asyncio.run(
        n8n_api._psychology_brief_stage(
            {
                "topic": "为什么越重要的消息越容易拖着不回？",
                "context": "聊天软件",
                "deliver_feishu": False,
            }
        )
    )

    assert result["run_id"] == "run-psych"
    assert result["delivery"] is None
    assert captured["topic"] == "为什么越重要的消息越容易拖着不回？"
    assert captured["context"] == "聊天软件"
    assert captured["run_id"] == "run-psych"


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "topic must be a string"),
        ({"topic": "合格选题", "context": 1}, "context must be a string"),
        (
            {"topic": "合格选题", "deliver_feishu": "yes"},
            "deliver_feishu must be a boolean",
        ),
    ],
)
def test_psychology_brief_stage_validates_input(payload, error):
    with pytest.raises(ValueError, match=error):
        asyncio.run(n8n_api._psychology_brief_stage(payload))
