import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai.enricher import ContentEnricher, EnrichmentRejected
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentBlock,
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
        id="rss:test:item",
        source_type=SourceType.RSS,
        title="A technical release",
        url="https://example.com/item",
        content="A project released a new architecture.",
        published_at=datetime.now(timezone.utc),
        profile="tech-news",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-news", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8.5,
                reason="Important release",
                summary="A new architecture was released.",
                tags=["systems"],
            ),
        ),
    )


class FakeTools:
    names = {"web_search"}

    async def execute(self, request_id, block_id, tool, arguments):
        assert block_id == "background"
        assert tool == "web_search"
        assert arguments == {"query": "project architecture"}
        return ToolResult(
            request_id=request_id,
            block_id=block_id,
            tool=tool,
            results=[
                {
                    "title": "Project documentation",
                    "url": "https://docs.example.com/project",
                    "text": "Architecture background.",
                }
            ],
        )


def test_enrichment_generates_blocks_and_validated_sources():
    responses = iter(
        [
            json.dumps(
                {
                    "tool_requests": [
                        {
                            "block_id": "background",
                            "tool": "web_search",
                            "arguments": {"query": "project architecture"},
                            "purpose": "Explain the existing architecture",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "title": "新架構發佈",
                    "blocks": [
                        {
                            "id": "summary",
                            "title": "摘要",
                            "content": "項目發佈了新的架構，它改變了系統設計，並採用了新的邊界。",
                            "source_refs": [],
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "title": "新架構發佈",
                    "blocks": [
                        {
                            "id": "summary",
                            "type": "section",
                            "title": "摘要",
                            "content": "项目发布了新的架构，它改变了系统设计，并采用了新的边界。",
                            "source_refs": [],
                        },
                        {
                            "id": "background",
                            "type": "section",
                            "title": "未隔离的背景",
                            "content": "这个版本应被丢弃。",
                            "source_refs": [],
                        },
                    ],
                }
            ),
            json.dumps(
                {
                    "title": "",
                    "block": {
                        "id": "background",
                        "type": "section",
                        "title": "背景",
                        "content": "旧架构的背景信息。",
                        "source_refs": ["tool-1"],
                    },
                }
            ),
        ]
    )
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return next(responses)

    item = make_item()
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["zh"],
        tools=FakeTools(),
    )
    asyncio.run(enricher._enrich_item(item))

    artifact = item.processing.artifacts["zh"]
    assert artifact.title == "新架构发布"
    assert artifact.blocks[0].content == "项目发布了新的架构，它改变了系统设计，并采用了新的边界。"
    assert [block.id for block in artifact.blocks] == [
        "summary",
        "background",
    ]
    assert artifact.blocks[-1].title == "背景"
    assert artifact.blocks[0].primary is True
    assert artifact.blocks[1].primary is False
    assert artifact.blocks[-1].source_refs == ["tool-1-1"]
    assert artifact.sources[0].url == "https://docs.example.com/project"
    assert len(requests) == 4
    assert "explicitly mentioned in the item" in requests[0]["system"]
    assert "Treat the source item as the primary account" in requests[1]["system"]
    assert "Simplified Chinese (language tag `zh`)" in requests[1]["system"]
    assert "Treat the source item as the primary account" in requests[3]["system"]
    assert "https://docs.example.com/project" not in requests[1]["user"]
    assert "https://docs.example.com/project" in requests[3]["user"]


def test_game_profile_writes_first_artifact_as_one_editorial_composition():
    game_profiles = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
    )
    item = make_item()
    item.profile = "game-tech-daily"
    item.processing.classification.profile = "game-tech-daily"
    responses = iter(
        [
            json.dumps(
                {
                    "title": "一张牌留下了谁都能抢的条件",
                    "block": {
                        "id": "what_happened",
                        "title": "先看这件事",
                        "content": "打出的牌会留在桌面并改变下一次出牌。",
                        "source_refs": ["fact-1-1"],
                    },
                }
            ),
            json.dumps(
                {
                    "decision": "publish",
                    "insight": {
                        "id": "fresh_relationship",
                        "title": "真正好玩的地方",
                        "content": "帮助队友的动作也会给对手留下机会。",
                        "source_refs": ["fresh-1-1"],
                    },
                    "rejection_reason": "",
                }
            ),
            json.dumps(
                {
                    "question": {
                        "id": "systems_question",
                        "title": "再往下问一层",
                        "content": "当共享条件不断被双方利用时，优势会积累还是自行抵消？",
                        "source_refs": ["fact-1-1"],
                    }
                }
            ),
        ]
    )
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return next(responses)

    tool_results = [
        ToolResult(
            request_id="fact-1",
            block_id="what_happened",
            tool="web_search",
            results=[
                {
                    "title": "Rules",
                    "url": "https://example.com/rules",
                    "text": "Cards remain in a shared area.",
                }
            ],
        ),
        ToolResult(
            request_id="fresh-1",
            block_id="fresh_relationship",
            tool="web_search",
            results=[
                {
                    "title": "Design notes",
                    "url": "https://example.com/notes",
                    "text": "Both teams can use the condition.",
                }
            ],
        ),
    ]
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        game_profiles,
        ["zh"],
        tools=FakeTools(),
    )

    generated = asyncio.run(
        enricher._generate_artifact(
            item, game_profiles.get("game-tech-daily"), "zh", tool_results
        )
    )

    assert len(requests) == 3
    assert "以体验为中心的游戏设计编辑" in requests[0]["system"]
    assert "what_happened" in requests[0]["system"]
    assert "事件叙述" in requests[0]["system"]
    assert "你是第二位编辑" in requests[1]["system"]
    assert "选择、代价、限制、反馈和不确定性" in requests[1]["system"]
    assert "系统追问者" in requests[2]["system"]
    assert "开放复杂巨系统" in requests[2]["system"]
    assert "# Event narration from the first editor" in requests[1]["user"]
    assert "# Event narration from the first editor" in requests[2]["user"]
    assert "# Core discovery from the second editor" in requests[2]["user"]
    assert "https://example.com/rules" in requests[0]["user"]
    assert "https://example.com/notes" in requests[0]["user"]
    assert "https://example.com/notes" in requests[1]["user"]
    assert "https://example.com/rules" in requests[2]["user"]
    assert [block.id for block in generated.blocks] == [
        "what_happened",
        "fresh_relationship",
        "systems_question",
    ]
    assert generated.blocks[0].primary is True
    assert generated.blocks[0].title == "先看这件事"
    assert generated.blocks[0].content.endswith("下一次出牌。")
    assert generated.blocks[1].title == "真正好玩的地方"
    assert generated.blocks[1].content.endswith("留下机会。")
    assert generated.blocks[2].content.endswith("自行抵消？")


def test_game_profile_can_reject_when_no_core_discovery_is_defensible():
    game_profiles = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
    )
    item = make_item()
    item.profile = "game-tech-daily"
    item.processing.classification.profile = "game-tech-daily"
    responses = iter(
        [
            json.dumps(
                {
                    "title": "一件普通的发布",
                    "block": {
                        "id": "what_happened",
                        "title": "先看这件事",
                        "content": "项目发布了一个常规版本。",
                        "source_refs": [],
                    },
                }
            ),
            json.dumps(
                {
                    "decision": "reject",
                    "insight": None,
                    "rejection_reason": "只能得到适用于任何发布的通用结论。",
                }
            ),
        ]
    )

    async def complete(**kwargs):
        return next(responses)

    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        game_profiles,
        ["zh"],
        tools=FakeTools(),
    )

    with pytest.raises(EnrichmentRejected, match="通用结论"):
        asyncio.run(
            enricher._generate_artifact(
                item, game_profiles.get("game-tech-daily"), "zh", []
            )
        )


def test_enrichment_rejects_tool_on_unapproved_block():
    async def complete(**kwargs):
        return json.dumps(
            {
                "tool_requests": [
                    {
                        "block_id": "summary",
                        "tool": "web_search",
                        "arguments": {"query": "unapproved"},
                        "purpose": "Rewrite the news",
                    }
                ]
            }
        )

    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["zh"],
        tools=FakeTools(),
    )

    with pytest.raises(ValueError, match="not allowed"):
        asyncio.run(enricher._enrich_item(make_item()))


def test_enrichment_rejects_malformed_tool_plan():
    async def complete(**kwargs):
        return "[]"

    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["zh"],
        tools=FakeTools(),
    )

    with pytest.raises(ValueError, match="tool plan"):
        asyncio.run(enricher._enrich_item(make_item()))


def test_enrichment_repairs_malformed_tool_plan_once():
    responses = iter(
        [
            "[]",
            json.dumps({"tool_requests": []}),
            json.dumps(
                {
                    "title": "Technical release",
                    "blocks": [
                        {
                            "id": "summary",
                            "type": "section",
                            "title": "Summary",
                            "content": "A complete summary.",
                            "source_refs": [],
                        },
                        {
                            "id": "background",
                            "type": "section",
                            "title": "Background",
                            "content": "Context for the release.",
                            "source_refs": [],
                        }
                    ],
                }
            ),
        ]
    )
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return next(responses)

    item = make_item()
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["en"],
        tools=FakeTools(),
    )

    asyncio.run(enricher._enrich_item(item))

    assert len(requests) == 3
    assert all(request["temperature"] == 0 for request in requests)
    assert requests[1]["temperature"] == 0
    assert item.processing.artifacts["en"].blocks[0].id == "summary"


def test_enrichment_repairs_empty_blog_block_once():
    responses = iter(
        [
            json.dumps(
                {
                    "title": "A technical story",
                    "blocks": [
                        {
                            "id": "background",
                            "title": " ",
                            "content": "",
                            "source_refs": [],
                        },
                        {
                            "id": "solution",
                            "title": "Solution and results",
                            "content": "The author explains the implementation.",
                            "source_refs": [],
                        },
                        {
                            "id": "takeaway",
                            "title": "Takeaway",
                            "content": "The approach is useful in bounded cases.",
                            "source_refs": [],
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "title": "A technical story",
                    "blocks": [
                        {
                            "id": "background",
                            "title": "Background",
                            "content": "The author frames the original problem and constraints.",
                            "source_refs": [],
                        },
                        {
                            "id": "solution",
                            "title": "Solution and results",
                            "content": "The author explains the implementation and its effects.",
                            "source_refs": [],
                        },
                        {
                            "id": "takeaway",
                            "title": "Takeaway",
                            "content": "The approach is useful in bounded cases.",
                            "source_refs": [],
                        }
                    ],
                }
            ),
        ]
    )
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return next(responses)

    item = make_item()
    item.profile = "tech-blog"
    item.processing.classification.profile = "tech-blog"
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["en"],
        tools=FakeTools(),
    )

    asyncio.run(enricher._enrich_item(item))

    assert len(requests) == 2
    assert requests[1]["temperature"] == 0
    assert "corrected JSON object" in requests[1]["user"]
    assert [
        block.id for block in item.processing.artifacts["en"].blocks
    ] == ["background", "solution", "takeaway"]
    assert all(
        not block.primary for block in item.processing.artifacts["en"].blocks
    )


def test_enrichment_repairs_schema_type_used_as_blog_block_id():
    responses = iter(
        [
            json.dumps(
                {
                    "title": "A technical story",
                    "blocks": [
                        {
                            "id": "section",
                            "type": "section",
                            "title": "Background",
                            "content": "A complete but misidentified background block.",
                            "source_refs": [],
                        },
                        {
                            "id": "solution",
                            "title": "Solution and results",
                            "content": "The implementation produced a measured result.",
                            "source_refs": [],
                        },
                        {
                            "id": "takeaway",
                            "title": "Takeaway",
                            "content": "The method has a clear bounded use.",
                            "source_refs": [],
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "title": "A technical story",
                    "blocks": [
                        {
                            "id": "background",
                            "title": "Background",
                            "content": "The corrected background and constraints.",
                            "source_refs": [],
                        },
                        {
                            "id": "solution",
                            "title": "Solution and results",
                            "content": "The implementation produced a measured result.",
                            "source_refs": [],
                        },
                        {
                            "id": "takeaway",
                            "title": "Takeaway",
                            "content": "The method has a clear bounded use.",
                            "source_refs": [],
                        }
                    ],
                }
            ),
        ]
    )
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return next(responses)

    item = make_item()
    item.profile = "tech-blog"
    item.processing.classification.profile = "tech-blog"
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["en"],
        tools=FakeTools(),
    )

    asyncio.run(enricher._enrich_item(item))

    assert len(requests) == 2
    assert "unknown blocks: section" in requests[1]["user"]
    assert item.processing.artifacts["en"].blocks[0].id == "background"


def test_failed_reenrichment_removes_stale_target_artifact():
    async def complete(**kwargs):
        return json.dumps(
            {
                "title": "A technical story",
                "blocks": [
                    {
                        "id": "story",
                        "type": "section",
                        "title": "",
                        "content": "",
                        "source_refs": [],
                    }
                ],
            }
        )

    item = make_item()
    item.profile = "tech-blog"
    item.processing.classification.profile = "tech-blog"
    item.processing.artifacts["en"] = ContentArtifact(
        language="en",
        title="Stale story",
    )
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["en"],
        tools=FakeTools(),
    )

    with pytest.raises(ValueError, match="Invalid enrichment artifact"):
        asyncio.run(enricher._enrich_item(item))

    assert "en" not in item.processing.artifacts


def test_enrichment_rejects_cross_block_source_reference():
    block = ContentBlock(
        id="summary",
        type="section",
        title="News",
        content="Content",
        source_refs=["tool-1-1"],
    )
    tool_result = ToolResult(
        request_id="tool-1",
        block_id="background",
        tool="web_search",
        results=[
            {
                "title": "Source",
                "url": "https://example.com/source",
                "text": "Context",
            }
        ],
    )

    with pytest.raises(ValueError, match="unknown source refs"):
        ContentEnricher._validate_blocks(
            [block], PROFILES.get("tech-news"), [tool_result]
        )


def test_enrichment_rejects_empty_required_block():
    block = ContentBlock(
        id="summary",
        type="section",
        title=" ",
        content="",
        source_refs=[],
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        ContentEnricher._validate_blocks(
            [block], PROFILES.get("tech-news"), []
        )


def test_enrichment_batch_reports_failure_without_discarding_successes():
    async def complete(**kwargs):
        raise RuntimeError("AI unavailable")

    successful_item = make_item()
    failed_item = make_item().model_copy(update={"id": "rss:test:failed"})
    enricher = ContentEnricher(
        SimpleNamespace(complete=complete),
        PROFILES,
        ["zh"],
        tools=FakeTools(),
    )

    async def enrich_item(item):  # type: ignore[no-untyped-def]
        if item.id == failed_item.id:
            raise RuntimeError("AI unavailable")

    enricher._enrich_item = enrich_item  # type: ignore[method-assign]

    result = asyncio.run(enricher.enrich_batch([successful_item, failed_item]))

    assert result.status == "partial_failure"
    assert result.succeeded_ids == [successful_item.id]
    assert result.failed_ids == [failed_item.id]
    assert result.failures[failed_item.id] == "RuntimeError: AI unavailable"


def test_enrichment_batch_keeps_editorial_rejections_separate_from_failures():
    accepted_item = make_item()
    rejected_item = make_item().model_copy(update={"id": "rss:test:rejected"})
    enricher = ContentEnricher(
        SimpleNamespace(complete=None),
        PROFILES,
        ["zh"],
        tools=FakeTools(),
    )

    async def enrich_item(item):  # type: ignore[no-untyped-def]
        if item.id == rejected_item.id:
            raise EnrichmentRejected("发现依赖通用联想")

    enricher._enrich_item = enrich_item  # type: ignore[method-assign]

    result = asyncio.run(enricher.enrich_batch([accepted_item, rejected_item]))

    assert result.status == "success"
    assert result.succeeded_ids == [accepted_item.id]
    assert result.rejected_ids == [rejected_item.id]
    assert result.rejections[rejected_item.id] == "发现依赖通用联想"
    assert result.failures == {}
