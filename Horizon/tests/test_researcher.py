import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.ai.enricher import ContentEnricher
from src.ai.researcher import ContentResearcher, research_prompt
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry
from src.processing.tools import ToolResult


PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "tech-news"
)


def make_item() -> ContentItem:
    return ContentItem(
        id="rss:test:omens",
        source_type=SourceType.RSS,
        title="Omens card game",
        url="https://example.com/omens",
        content="Omens is a team card game.",
        published_at=datetime.now(timezone.utc),
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-news", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8.5,
                reason="Concrete interaction",
                summary="Cards affect allies and opponents.",
                tags=["cards"],
            ),
        ),
    )


class FakeTools:
    names = {"web_search"}

    async def execute(self, request_id, block_id, tool, arguments):
        assert block_id == "research"
        assert tool == "web_search"
        return ToolResult(
            request_id=request_id,
            block_id=block_id,
            tool=tool,
            results=[
                {
                    "title": f"Result for {arguments['query']}",
                    "url": f"https://example.com/result-{request_id}",
                    "text": "Concrete rules and interaction details.",
                }
            ],
        )


def test_researcher_attaches_reusable_subject_and_similarity_results():
    async def complete(**kwargs):
        return json.dumps(
            {
                "focus": "Omens timing interactions",
                "requests": [
                    {
                        "kind": "subject",
                        "query": "Omens card game rules",
                        "purpose": "Check the original rules",
                    },
                    {
                        "kind": "similar",
                        "query": "team card games shared tableau interaction",
                        "purpose": "Find a close mechanism comparison",
                    },
                ]
            }
        )

    item = make_item()
    researcher = ContentResearcher(
        SimpleNamespace(complete=complete), PROFILES, tools=FakeTools()
    )

    asyncio.run(researcher._research_item(item))

    research = item.metadata["mechanism_research"]
    assert research["status"] == "success"
    assert research["focus"] == "Omens timing interactions"
    assert [request["kind"] for request in research["requests"]] == [
        "subject",
        "similar",
    ]
    assert research["requests"][0]["results"][0]["url"].startswith(
        "https://example.com/result-research-"
    )

    profile = PROFILES.get("tech-news")
    preloaded = ContentEnricher._research_tool_results(item, profile)
    assert {result.block_id for result in preloaded} == {"background"}
    assert len(preloaded) == 2


def test_game_research_uses_editorial_stance_without_writing_the_article():
    profiles = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
    )

    prompt = research_prompt(profiles.get("game-tech-daily"))

    assert "以体验为中心的游戏设计编辑" in prompt
    assert "which missing fact could genuinely change" in prompt
    assert "Do not write the final article" in prompt
