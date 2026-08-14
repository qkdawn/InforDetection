from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.ai.selector import EditorialSelector
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry


PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
)


def make_item(
    item_id: str,
    score: float,
    source: str = "Feed",
    profile: str = "game-tech-daily",
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Title {item_id}",
        url=f"https://example.com/{item_id}",
        content="Concrete source content.",
        published_at=datetime.now(timezone.utc),
        metadata={"feed_name": source, "mechanism_research": {"status": "success"}},
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile=profile, method="source_override"
            ),
            analysis=ContentAnalysis(
                score=score,
                reason="Concrete relationship",
                summary="Useful finding",
            ),
        ),
    )


def test_light_evaluation_is_stored_on_item_metadata() -> None:
    async def complete(**kwargs):
        return json.dumps(
            {
                "factual_core": "A verified event",
                "fresh_relationship": "A changes B through C",
                "game_design_value": "Supports a readable feedback loop",
                "evidence_quality": 8,
                "design_potential": 9,
                "visual_potential": 7,
                "novelty": 8,
                "confidence": 0.9,
                "rejection_risk": None,
            }
        )

    item = make_item("item-1", 8.5)
    selector = EditorialSelector(SimpleNamespace(complete=complete), PROFILES)

    result = asyncio.run(selector.evaluate_batch([item]))

    assert result.status == "success"
    assert item.metadata["editorial_evaluation"]["design_potential"] == 9


def test_final_selection_uses_exact_ai_ids_and_order() -> None:
    async def complete(**kwargs):
        return json.dumps(
            {
                "selected": [
                    {"id": "item-2", "rank": 1, "reason": "strongest"},
                    {"id": "item-1", "rank": 2, "reason": "complements it"},
                ],
                "summary": "A diverse set",
            }
        )

    items = [
        make_item("item-1", 8, source="Feed A", profile="game-tech-daily"),
        make_item("item-2", 9, source="Feed B", profile="tech-news"),
        make_item("item-3", 7.5, source="Feed C", profile="game-tech-daily"),
    ]
    for item in items:
        item.metadata["editorial_evaluation"] = {
            "design_potential": 8,
            "evidence_quality": 8,
        }
    selector = EditorialSelector(SimpleNamespace(complete=complete), PROFILES)

    selected, decision = asyncio.run(
        selector.select(items, limit=2, min_topics=2, max_per_source=1)
    )

    assert [item.id for item in selected] == ["item-2", "item-1"]
    assert decision["method"] == "ai_jury"
