from pathlib import Path
from datetime import datetime, timezone

from src.ai.prompting.enrichment import (
    artifact_prompt,
    block_prompt,
    editorial_tool_results_text,
    event_narration_prompt,
    game_insight_prompt,
    item_context,
    source_read_planning_prompt,
    systems_question_prompt,
    tool_planning_prompt,
)
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry


PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "tech-news"
)


def test_tool_planning_excludes_profile_writing_policy():
    profile = PROFILES.get("tech-news")
    blocks = profile.definition.enrichment.blocks

    planning = tool_planning_prompt(profile, blocks)
    artifact = artifact_prompt(profile, "en", blocks)
    block = block_prompt(profile, "en", blocks[0], include_header=True)

    assert profile.enrichment_prompt not in planning
    assert profile.enrichment_prompt in artifact
    assert profile.enrichment_prompt in block
    assert all(configured.id in planning for configured in blocks)
    assert "Block `background` is required" in planning


def test_enrichment_context_uses_profile_content_budget():
    profile = PROFILES.get("tech-blog")
    item = ContentItem(
        id="rss:test:blog",
        source_type=SourceType.RSS,
        title="Long article",
        url="https://example.com/blog",
        published_at=datetime.now(timezone.utc),
        profile="tech-blog",
        content="OPENING" + "A" * 25000 + "MIDDLE" + "B" * 25000 + "ENDING",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-blog", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8,
                reason="Deep article",
                summary="A long argument",
            ),
        ),
    )

    context = item_context(item, profile, include_content=True)

    assert "[Opening excerpt]" in context
    assert "[Middle excerpt]" in context
    assert "[Closing excerpt]" in context
    assert "OPENING" in context
    assert "MIDDLE" in context
    assert "ENDING" in context


def test_editorial_references_are_deduplicated_without_losing_block_citations():
    from src.processing.tools import ToolResult

    shared = {
        "title": "Shared evidence",
        "url": "https://example.com/shared",
        "text": "One concrete fact.",
    }
    rendered = editorial_tool_results_text(
        [
            ToolResult(
                request_id="fact-1",
                block_id="what_happened",
                tool="web_search",
                results=[shared],
            ),
            ToolResult(
                request_id="relation-1",
                block_id="fresh_relationship",
                tool="web_search",
                results=[shared],
            ),
        ]
    )

    assert rendered.count("https://example.com/shared") == 1
    assert "`fact-1-1` for block `what_happened`" in rendered
    assert "`relation-1-1` for block `fresh_relationship`" in rendered


def test_editorial_generation_uses_separate_event_and_insight_prompts():
    profiles = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
    )
    profile = profiles.get("game-tech-daily")
    event = event_narration_prompt(
        profile, "zh", profile.definition.enrichment.blocks[0]
    )
    insight = game_insight_prompt(
        profile, "zh", profile.definition.enrichment.blocks[1]
    )
    source_read = source_read_planning_prompt(profile, "zh")
    systems = systems_question_prompt(
        profile, "zh", profile.definition.enrichment.blocks[2]
    )

    assert "what_happened" in event
    assert '"event_card"' not in event
    assert '"condition"' not in event
    assert "事件叙述" in event
    assert "资深游戏设计师和游戏体验研究者" in insight
    assert "隐藏的“玩家体验结构”" in insight
    assert "`read_source` tool" in source_read
    assert '"mode": "sample" or "search"' in source_read
    assert '"decision": "publish" or "reject"' in insight
    assert '"rejection_reason"' in insight
    assert '"insight_card"' not in insight
    assert '"previous_understanding"' not in insight
    assert '"new_understanding"' not in insight
    assert '"design_takeaway"' not in insight
    assert '"changed_relationship"' not in insight
    assert "Privately test several lenses" not in insight
    assert "short, surprising" not in insight
    assert "fixed questionnaire" not in insight
    assert "analysis reason only as a hypothesis" not in insight
    assert "开放复杂巨系统" in systems
    assert "进一步的观察、讨论、建模或游戏实验" in systems
    assert '"id": "systems_question"' in systems
