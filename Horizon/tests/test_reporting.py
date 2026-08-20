from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.reporting import (
    BODY_FONT_FAMILY,
    COVER_ACCENT,
    PRODUCT_COLOR,
    REPORT_THEME,
    TOPIC_CARD_THEMES,
    TITLE_FONT_FAMILY,
    build_card_html,
    build_markdown,
    build_report_model,
    generate_xiaohongshu_report,
)


def _item(
    item_id: str,
    score: float,
    category: str = "玩家行为与涌现玩法",
    profile: str = "player-market",
) -> dict:
    return {
        "id": item_id,
        "title": f"Original {item_id}",
        "url": f"https://example.com/{item_id}",
        "content": "<p>Body</p>",
        "published_at": "2026-08-01T08:00:00Z",
        "metadata": {"feed_name": "Example", "category": category},
        "processing": {
            "classification": {
                "profile": profile,
                "method": "ai_match",
            },
            "analysis": {"score": score, "summary": "fallback", "tags": ["AI"]},
            "artifacts": {
                "zh": {
                    "title": f"中文标题 {item_id}",
                    "blocks": [
                        {
                            "id": "what_happened",
                            "primary": True,
                            "title": f"事件标题 {item_id}",
                            "content": f"发生过程 {item_id}",
                        },
                        {
                            "id": "mechanism_chain",
                            "content": "前一步 → 留下条件 → 后一步利用",
                        },
                        {
                            "id": "fresh_relationship",
                            "title": f"设计标题 {item_id}",
                            "content": f"新鲜关系 {item_id}",
                        },
                        {
                            "id": "systems_question",
                            "title": f"系统标题 {item_id}",
                            "content": f"系统继续变化会发生什么 {item_id}？",
                        },
                        {
                            "id": "game_question",
                            "content": f"游戏问题 {item_id}",
                        },
                    ],
                }
            },
        },
    }


def _visual_batch(*, enabled: bool = True, failed: int = 0) -> dict:
    return {
        "enabled": enabled,
        "model": "test-image-model",
        "generated": 0,
        "cached": 0,
        "failed": failed,
        "images": [],
        "errors": {},
    }


def test_report_refuses_to_render_without_the_generated_cover(
    monkeypatch, tmp_path
) -> None:
    agent = MagicMock()
    agent.generate = AsyncMock(
        return_value={
            "concept_images": _visual_batch(),
            "mechanism_images": _visual_batch(),
            "composition_images": _visual_batch(enabled=False),
            "complete_items": 1,
            "orchestrated_items": 0,
            "requested_items": 1,
        }
    )
    monkeypatch.setattr("src.reporting.CardVisualAgent", lambda: agent)
    monkeypatch.setattr(
        "src.reporting.generate_cover_image",
        AsyncMock(
            return_value={
                "enabled": True,
                "image_url": None,
                "failed": 1,
                "error": "upstream_error: Upstream error, please retry.",
            }
        ),
    )

    with pytest.raises(RuntimeError, match="refusing to render a fallback cover"):
        asyncio.run(
            generate_xiaohongshu_report(
                run_id="run-missing-cover",
                items=[_item("cover", 9)],
                meta={"raw_count": 1, "date": "2026-08-18"},
                max_cards=4,
                output_root=tmp_path,
            )
        )


def test_report_refuses_to_render_without_every_concept_image(
    monkeypatch, tmp_path
) -> None:
    agent = MagicMock()
    agent.generate = AsyncMock(
        return_value={
            "concept_images": _visual_batch(failed=1),
            "mechanism_images": _visual_batch(),
            "composition_images": _visual_batch(enabled=False),
            "complete_items": 0,
            "orchestrated_items": 0,
            "requested_items": 1,
        }
    )
    monkeypatch.setattr("src.reporting.CardVisualAgent", lambda: agent)
    monkeypatch.setattr(
        "src.reporting.generate_cover_image",
        AsyncMock(
            return_value={
                "enabled": True,
                "image_url": "data:image/png;base64,COVER",
                "failed": 0,
                "error": None,
            }
        ),
    )

    with pytest.raises(RuntimeError, match="refusing to render fallback cards"):
        asyncio.run(
            generate_xiaohongshu_report(
                run_id="run-missing-concept",
                items=[_item("concept", 9)],
                meta={"raw_count": 1, "date": "2026-08-18"},
                max_cards=4,
                output_root=tmp_path,
            )
        )


def test_report_keeps_every_selected_item():
    model = build_report_model(
        run_id="run-test",
        items=[_item("b", 7), _item("a", 9, "动物、生态与自然现象")],
        meta={"created_at": "2026-08-01T01:00:00Z", "raw_count": 12},
    )
    markdown = build_markdown(model)

    assert model["date"] == "2026-08-01"
    assert [item["id"] for item in model["items"]] == ["a", "b"]
    assert "中文标题 a" in markdown
    assert "中文标题 b" in markdown
    assert "抓取 12 条" in markdown
    assert "**发生了什么：** 发生过程 a" in markdown
    assert "**机制链：** 前一步 → 留下条件 → 后一步利用" in markdown
    assert "**真正好玩的地方：** 新鲜关系 a" in markdown
    assert "**再往下问一层：** 系统继续变化会发生什么 a？" in markdown
    assert "**它可能启发哪一类游戏问题：** 游戏问题 b" in markdown
    assert "为什么可玩" not in markdown
    assert "玩家怎么选" not in markdown
    assert "先验证什么" not in markdown
    assert "游戏创意雷达" in markdown
    assert "抽象模型" not in markdown


def test_report_preserves_editorial_paragraphs_and_bold_emphasis():
    item = _item("rich-copy", 9)
    blocks = item["processing"]["artifacts"]["zh"]["blocks"]
    blocks[0]["content"] = (
        "第一段先讲清变化，**身体先于地图读懂海面**。\n\n"
        "第二段说明这种变化如何影响下一次判断。"
    )
    blocks[2]["content"] = (
        "空间不只是等待辨认的物体。\n\n"
        "它也可以成为**一组先于物体显现的后果**。"
    )
    blocks[3]["content"] = (
        "行动改变了下一次能够获得的线索。\n\n"
        "连续反馈也可能**把错误理解固化成习惯**。"
    )

    model = build_report_model(
        run_id="run-rich-copy",
        items=[item],
        meta={"raw_count": 1},
    )
    markdown = build_markdown(model)
    cards = build_card_html(model, max_cards=4)
    card = "".join(spec["html"] for spec in cards[2:4])

    assert model["items"][0]["what_happened"] == (
        "第一段先讲清变化，身体先于地图读懂海面。 "
        "第二段说明这种变化如何影响下一次判断。"
    )
    assert "**身体先于地图读懂海面**。\n\n第二段" in markdown
    assert "**一组先于物体显现的后果**" in markdown
    assert "<p>第一段先讲清变化，<strong>身体先于地图读懂海面</strong>。</p>" in card
    assert "<p>第二段说明这种变化如何影响下一次判断。</p>" in card
    assert "<strong>把错误理解固化成习惯</strong>" in card
    assert "**身体先于地图读懂海面**" not in card
    assert ".rich-copy p + p { margin-top: calc(9px * var(--copy-scale)); }" in card
    assert ".rich-copy strong { color:" in card
    assert "font-size: inherit; font-weight: 900;" in card
    assert "copy.querySelector('.rich-copy')" in card
    assert "const contentOverflows = (element)" in card
    assert "'.panel-heading, .rich-copy p'" in card
    assert "nodeBounds.bottom > bottom + 1" in card


def test_report_reduces_unapproved_markdown_and_html_to_safe_copy():
    item = _item("safe-copy", 9)
    blocks = item["processing"]["artifacts"]["zh"]["blocks"]
    blocks[2]["content"] = (
        "<script>alert('unsafe')</script>第一段包含[外链](https://example.com)。\n\n"
        "## 不应成为标题\n\n- 不应成为列表\n\n"
        "普通的**允许重点**仍然保留。"
    )

    model = build_report_model(
        run_id="run-safe-copy",
        items=[item],
        meta={"raw_count": 1},
    )
    markdown = build_markdown(model)
    card = build_card_html(model, max_cards=4)[3]["html"]

    assert "alert('unsafe')" not in card
    assert "<a " not in card
    assert "<h2>不应成为标题</h2>" not in card
    assert "<ul" not in card
    assert "<li" not in card
    assert "href=" not in card
    assert "<strong>允许重点</strong>" in card
    assert "[外链](https://example.com)" not in markdown
    assert "**允许重点**" in markdown


def test_card_deck_respects_limit_without_truncating_report_model():
    model = build_report_model(
        run_id="run-test",
        items=[_item(str(index), 10 - index / 10) for index in range(20)],
        meta={"raw_count": 20},
    )
    cards = build_card_html(model, max_cards=12)

    assert len(model["items"]) == 20
    assert len(cards) == 22
    assert cards[0]["slug"] == "cover"
    assert cards[1]["slug"] == "directory"
    assert cards[2]["slug"] == "item-01"
    assert cards[-1]["slug"] == "item-10-detail"
    assert "值得偷走的" in cards[0]["html"]
    assert "从真实世界" in cards[0]["html"]
    assert "长出游戏" in cards[0]["html"]
    assert "从今日 20 条现实材料里" in cards[0]["html"]
    assert "cover-count-panel" in cards[0]["html"]
    assert "cover-taxonomy" in cards[0]["html"]
    assert "中文标题 0" in cards[1]["html"]
    assert "中文标题 19" in cards[1]["html"]
    assert "事件" in cards[2]["html"]
    assert "设计启示" not in cards[2]["html"]
    assert "系统追问" not in cards[2]["html"]
    assert "事件过程" in cards[2]["html"]
    assert '<div class="event-index">' in cards[2]["html"]
    assert '<div class="event-index">\n              <b>事件</b>' in cards[2]["html"]
    assert "<strong>00</strong>" not in cards[2]["html"]
    assert "insight-symbol" not in cards[2]["html"]
    assert '<i></i><b>事件过程</b></div>' in cards[2]["html"]
    assert "MECHANIC<br>BREAKDOWN" not in cards[2]["html"]
    assert '<i></i><b>设计启示</b></div>' in cards[3]["html"]
    assert '<i></i><b>系统追问</b></div>' in cards[3]["html"]
    assert "DESIGN<br>IMPLICATIONS" not in cards[2]["html"]
    assert "EXTENDED<br>THOUGHT" not in cards[2]["html"]
    assert 'class="panel-kicker"' not in cards[2]["html"]
    assert "为什么成立" not in cards[2]["html"]
    assert "一句话洞察" not in cards[2]["html"]
    assert "这件事改写了什么" not in cards[2]["html"]
    assert "延伸思考" not in cards[2]["html"]
    assert "系统继续变化会发生什么 0？" in cards[3]["html"]
    assert "mechanism-board" in cards[2]["html"]
    assert "事件标题 0" in cards[2]["html"]
    assert "发生过程 0" in cards[2]["html"]
    assert "设计标题 0" in cards[3]["html"]
    assert "新鲜关系 0" in cards[3]["html"]
    assert "系统标题 0" in cards[3]["html"]
    assert "原有理解 0" not in cards[2]["html"]
    assert "新理解 0" not in cards[2]["html"]
    assert "设计带走 0" not in cards[2]["html"]
    assert "事件中的条件" not in cards[2]["html"]
    assert "它可能启发哪一类游戏问题" not in cards[2]["html"]
    assert "可以怎么玩" not in cards[2]["html"]
    assert "为什么可玩" not in cards[2]["html"]
    assert "生成方法" not in "".join(card["html"] for card in cards)
    assert 'class="page cover-page"' in cards[0]["html"]
    assert 'class="page directory-page"' in cards[1]["html"]
    assert 'class="page item-page event-card-layout"' in cards[2]["html"]
    assert f'--paper: {REPORT_THEME["paper"]}' in cards[0]["html"]
    assert ".cover-page { background: #F0EBDC" in cards[0]["html"]
    assert ".item-page { background: var(--paper)" in cards[2]["html"]
    assert (
        ".cover-count-panel { position: absolute; right: 54px; "
        "top: 100px; width: 316px; height: 316px; padding: 38px 28px 24px; "
        f"background: {COVER_ACCENT};"
    ) in cards[0]["html"]
    assert f".directory-row strong {{ color: {COVER_ACCENT};" in cards[1]["html"]
    assert PRODUCT_COLOR != COVER_ACCENT
    assert (
        f".editorial-tag {{ display: inline-flex; max-width: 240px; padding: 8px 12px; border: 1px solid {REPORT_THEME['moss']};"
        in cards[2]["html"]
    )
    assert all("1080px" in card["html"] and "1440px" in card["html"] for card in cards)


def test_cover_prefers_daily_cover_art_over_lead_item_image():
    model = build_report_model(
        run_id="run-cover-art",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["cover_image_url"] = "data:image/png;base64,DAILY-COVER"

    cover = build_card_html(model, max_cards=3)[0]["html"]

    assert "data:image/png;base64,DAILY-COVER" in cover


def test_report_drops_item_when_core_discovery_is_missing():
    item = _item("standalone", 9)
    item["processing"]["artifacts"]["zh"]["blocks"] = [
        {
            "id": "what_happened",
            "primary": True,
            "content": "一段完整的编辑主稿，已经包含事实、关系和启发。",
        }
    ]
    model = build_report_model(
        run_id="run-standalone-editorial",
        items=[item],
        meta={"raw_count": 1},
    )

    markdown = build_markdown(model)
    cards = build_card_html(model, max_cards=3)

    assert model["items"] == []
    assert "一段完整的编辑主稿" not in markdown
    assert len(cards) == 2


def test_empty_report_explains_that_all_candidates_were_rejected():
    model = build_report_model(
        run_id="run-all-rejected",
        items=[],
        meta={
            "raw_count": 12,
            "filtered_count": 3,
            "enriched_count": 0,
            "enrichment_rejected_count": 3,
        },
    )

    markdown = build_markdown(model)
    cards = build_card_html(model, max_cards=3)

    assert model["selected"] == 0
    assert "候选材料经过深挖后全部退稿" in model["overview"]
    assert "深挖退稿（3 条）" in markdown
    assert "退稿原因" not in markdown
    assert "今天不硬凑" in cards[0]["html"]


def test_card_displays_the_native_mechanism_visual_without_empty_side_bands():
    model = build_report_model(
        run_id="run-mechanism-art",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["mechanism_image_url"] = "data:image/png;base64,MECHANISM-ART"

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert card.count('class="mechanism-strip"') == 1
    assert card.count("data:image/png;base64,MECHANISM-ART") == 1
    assert "object-fit: cover" in card
    assert "object-position: 50% 50%" in card
    assert "transform: scale(1.045)" in card
    assert ".mechanism-board { position: absolute; left: 0; right: 0; top: 662px; height: 352px" in card
    assert ".event-strip { --copy-scale: 1; position: absolute; left: 0; right: 0; top: 452px" in card
    assert ".bottom-board { position: absolute; left: 0; right: 0; top: 1014px" in card
    assert ".mechanism-strip { position: absolute; inset: 2px 0" in card
    assert "border-radius: 0" in card
    assert 'class="media-fit"' in card
    assert 'class="mechanism-fallback"' not in card


def test_item_card_uses_its_topic_palette():
    model = build_report_model(
        run_id="run-warm-paper-card",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    topic_theme = TOPIC_CARD_THEMES["player-market"]
    assert f'--paper: {topic_theme["paper"]}' in card
    assert f'--paper-soft: {topic_theme["paper_soft"]}' in card
    assert f'--panel: {topic_theme["panel"]}' in card
    assert f'--ink: {topic_theme["ink"]}' in card
    assert f'--muted: {topic_theme["muted"]}' in card
    assert f'--line: {topic_theme["line"]}' in card


def test_report_uses_the_original_deep_green_as_its_dominant_surface():
    assert REPORT_THEME["green"] == "#16372F"
    assert REPORT_THEME["paper"] == "#061812"
    assert REPORT_THEME["paper_soft"] == "#0B2119"
    assert REPORT_THEME["brand"] == "#E46B5B"
    assert PRODUCT_COLOR == REPORT_THEME["brand"]
    assert COVER_ACCENT == "#D6BC63"


def test_item_card_uses_light_ink_for_long_form_body_copy():
    model = build_report_model(
        run_id="run-readable-body-copy",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert ".agent-body { margin: 0; color: var(--ink);" in card
    assert ".panel-body { color: var(--ink);" in card
    assert ".item-page { background: var(--paper)" in card
    assert ".editorial-title" in card
    assert "color: var(--ink)" in card
    assert ".event-strip {" in card
    assert "background: var(--paper-soft)" in card
    assert ".bottom-board {" in card
    assert "top: 1014px; bottom: 24px;" in card
    assert "top: 1074px; height: 262px;" not in card
    assert "z-index: 10; left: 40px; right: 40px; bottom: 3px; height: 18px;" in card
    assert 'class="editorial-footer"' in card


def test_report_hides_internal_research_citation_ids_from_reader_copy():
    item = _item("citations", 9)
    blocks = item["processing"]["artifacts"]["zh"]["blocks"]
    blocks[0]["content"] = (
        "正文事实。[research-what_happened-1-1] "
        "下一句。[tool-2-3] "
        "圆括号（research-what_happened-1-1, "
        "research-fresh_relationship-1-1）。"
    )
    blocks[2]["content"] = (
        "设计关系。[research-fresh_relationship-1-1]"
        "[research-fresh_relationship-2-3]"
        "中文括号【research-fresh_relationship-2-2】。"
        "英文括号(tool-2-3, research-fresh_relationship-1-1)。"
        "裸编号 research-fresh_relationship-3-1 不展示。"
    )
    model = build_report_model(
        run_id="run-hidden-citations",
        items=[item],
        meta={"raw_count": 1},
    )

    markdown = build_markdown(model)
    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert "正文事实。 下一句。" in markdown
    assert "设计关系。中文括号" in card
    assert "圆括号。" in markdown
    assert "英文括号。裸编号 不展示。" in card
    assert "[research-" not in markdown
    assert "[research-" not in card
    assert "[tool-" not in markdown
    assert "[tool-" not in card
    assert "【research-" not in markdown
    assert "【research-" not in card
    assert "research-" not in markdown
    assert "research-" not in card


def test_item_card_body_type_is_readable_at_thumbnail_size():
    model = build_report_model(
        run_id="run-readable-type",
        items=[_item("type", 9)],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert "calc(25px * var(--copy-scale))/1.3" in card
    assert "calc(20px * var(--copy-scale))/1.32" in card
    assert "calc(17px * var(--copy-scale))/1.58" in card
    assert "calc(15px * var(--copy-scale))/1.58" in card
    assert "const minimum = 0.64" in card
    assert "for (let attempt = 0; attempt < 10; attempt += 1)" in card
    assert "clampToWholeLines" in card
    assert "webkitLineClamp" in card
    assert "copy.dataset.overflow" in card


def test_insight_card_stacks_sections_vertically_at_full_width():
    model = build_report_model(
        run_id="run-vertical-insight-layout",
        items=[_item("vertical", 9)],
        meta={"raw_count": 1},
    )

    detail_card = build_card_html(model, max_cards=4)[3]["html"]

    assert 'class="page item-page insight-card-layout"' in detail_card
    assert (
        ".insight-card-layout .bottom-board { top: 72px; bottom: 24px; "
        "grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }"
    ) in detail_card
    assert '<section class="editorial-hero">' not in detail_card
    assert 'class="editorial-tags"' not in detail_card
    assert 'class="editorial-title"' not in detail_card
    assert (
        ".insight-card-layout .panel-heading { "
        "font-size: calc(32px * var(--copy-scale));"
    ) in detail_card
    assert (
        ".insight-card-layout .panel-body { "
        "font-size: calc(28px * var(--copy-scale));"
    ) in detail_card
    assert (
        ".insight-card-layout .question-panel { border-left: 0; "
        "border-top: 1px solid"
    ) in detail_card
    assert (
        ".insight-card-layout .design-panel, .insight-card-layout .question-panel "
        "{ grid-template-columns: 120px minmax(0, 1fr); }"
    ) in detail_card
    assert (
        ".event-card-layout .section-index strong, "
        ".insight-card-layout .section-index strong { font-size: 30px; }"
    ) in detail_card
    assert "font-size: 30px; font-weight: 900;" in detail_card
    assert "writing-mode: vertical-rl; text-orientation: upright;" in detail_card


def test_event_copy_is_vertically_centered_beside_its_heading():
    model = build_report_model(
        run_id="run-centered-event-copy",
        items=[_item("event", 9)],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert (
        ".event-body { --copy-scale: 1; height: 178px; padding: 0 30px; "
        "display: flex; align-items: center; overflow: hidden; }"
    ) in card
    assert (
        ".event-card-layout .event-body { height: 100%; padding: 34px 42px; "
        "align-items: center;"
    ) in card
    assert (
        ".event-card-layout .agent-lead { align-items: center; padding: 40px 18px; "
        "text-align: center; }"
    ) in card
    assert "text-align: center; text-wrap: balance;" in card
    assert "<h2 data-fit-event-heading>" in card
    assert "const fitEventHeading = (heading)" in card
    assert "const minimum = 28;" in card
    assert "heading.dataset.lines = 'single';" in card
    assert "heading.dataset.lines = 'wrapped';" in card


def test_event_and_insight_cards_split_their_lower_sections_evenly():
    model = build_report_model(
        run_id="run-primary-copy-space",
        items=[_item("event-space", 9)],
        meta={"raw_count": 1},
    )

    card = build_card_html(model, max_cards=4)[2]["html"]

    assert (
        ".event-card-layout .event-strip { top: 452px; height: 482px; "
        "align-items: stretch; }"
    ) in card
    assert (
        ".event-card-layout .mechanism-board { top: 934px; bottom: 24px; "
        "height: auto; grid-template-columns: 120px minmax(0, 1fr); }"
    ) in card
    assert (
        ".event-card-layout .section-index b, "
        ".insight-card-layout .section-index b { margin: 0;"
    ) in card
    assert "font-size: 30px; font-weight: 900;" in card
    assert "writing-mode: vertical-rl; text-orientation: upright;" in card

    insight_card = build_card_html(model, max_cards=4)[3]["html"]
    assert (
        ".insight-card-layout .bottom-board { top: 72px; bottom: 24px; "
        "grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }"
    ) in insight_card


def test_report_embeds_reusable_display_and_body_font_roles():
    model = build_report_model(
        run_id="run-round-title-font",
        items=[_item("type", 9)],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert f'font-family: "{TITLE_FONT_FAMILY}"' in card
    assert f'font-family: "{BODY_FONT_FAMILY}"' in card
    assert card.count("data:font/woff2;base64,") == 4
    assert f'--font-display: "{TITLE_FONT_FAMILY}"' in card
    assert f'--font-body: "{BODY_FONT_FAMILY}"' in card
    assert "font: 400 60px/1.12 var(--font-display)" in card
    assert (
        "font: 700 calc(17px * var(--copy-scale))/1.58 var(--font-body)"
        in card
    )
    assert "font: 500 14px var(--font-mono)" in card


def test_report_css_uses_branded_cover_and_topic_surface_tokens():
    model = build_report_model(
        run_id="run-paper-only-theme",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )

    html = "".join(card["html"] for card in build_card_html(model, max_cards=3))

    for token in (
        REPORT_THEME["green"],
        REPORT_THEME["paper"],
        TOPIC_CARD_THEMES["player-market"]["paper"],
        TOPIC_CARD_THEMES["player-market"]["panel"],
        TOPIC_CARD_THEMES["player-market"]["green_mid"],
        "#315C50",
    ):
        assert token.lower() in html.lower()

    for archival_token in (
        "#f1eadb",
        "#e5dac5",
        "#2d2923",
        "#c94f3d",
        "#6d5bd0",
        "#d43d74",
        "#e84a3c",
    ):
        assert archival_token not in html.lower()


def test_each_content_topic_gets_a_distinct_complete_card_theme():
    topic_ids = [
        "gameplay-mechanics",
        "world-level",
        "narrative-culture",
        "visual-experience",
        "player-market",
        "production-tech",
    ]
    model = build_report_model(
        run_id="run-topic-themes",
        items=[_item(topic_id, 9, profile=topic_id) for topic_id in topic_ids],
        meta={"raw_count": len(topic_ids)},
    )

    cards = build_card_html(model, max_cards=14)
    item_cards = cards[2::2]

    assert len({theme["paper"] for theme in TOPIC_CARD_THEMES.values()}) == 6
    assert len(item_cards) == 6
    for card, item in zip(item_cards, model["items"], strict=True):
        theme = TOPIC_CARD_THEMES[item["section_id"]]
        assert f'--paper: {theme["paper"]}' in card["html"]
        assert f'--ink: {theme["ink"]}' in card["html"]
        assert f'--question-surface: {theme["question_surface"]}' in card["html"]


def test_card_ignores_legacy_composition_image_layer():
    model = build_report_model(
        run_id="run-composition-art",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["composition_image_url"] = "data:image/png;base64,COMPOSITION-ART"

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert 'class="composition-backdrop"' not in card
    assert "data:image/png;base64,COMPOSITION-ART" not in card


def test_card_uses_hero_only_once_without_a_background_copy():
    model = build_report_model(
        run_id="run-hero-atmosphere",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["concept_image_url"] = "data:image/png;base64,HERO-ART"
    model["items"][0]["composition_image_url"] = None

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert 'class="composition-backdrop is-hero-fallback"' not in card
    assert card.count("data:image/png;base64,HERO-ART") == 1
    assert "blur(24px)" not in card


def test_new_card_places_insight_before_mechanism_and_systems_question():
    model = build_report_model(
        run_id="run-visual-agent",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["mechanism_steps"] = []
    model["items"][0]["mechanism_image_url"] = "data:image/png;base64,VISUAL-AGENT-FLOW"

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    event_position = card.index('class="event-strip"')
    flow_position = card.index('class="mechanism-board"')
    design_position = card.index('data-field-label="设计启示"')
    question_position = card.index("系统继续变化会发生什么 a？")
    assert event_position < flow_position < design_position < question_position
    assert "VISUAL-AGENT-FLOW" in card
    assert 'class="bottom-board"' in card
    assert 'class="design-content" data-fit-copy' in card
    assert 'class="question-content" data-fit-copy' in card


def test_historical_card_without_systems_question_still_renders():
    item = _item("legacy", 9)
    blocks = item["processing"]["artifacts"]["zh"]["blocks"]
    item["processing"]["artifacts"]["zh"]["blocks"] = [
        block for block in blocks if block["id"] != "systems_question"
    ]
    for block in item["processing"]["artifacts"]["zh"]["blocks"]:
        block.pop("event_card", None)
        block.pop("insight_card", None)

    model = build_report_model(
        run_id="run-legacy-without-systems-question",
        items=[item],
        meta={"raw_count": 1},
    )
    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert model["items"][0]["systems_question"] == ""
    assert 'data-agent-copy="systems"' not in card
    assert "新鲜关系 legacy" in card


def test_source_art_does_not_replace_the_generated_concept_hero():
    item = _item("a", 9)
    item["content"] = '<p>Body</p><img src="https://example.com/item-art.jpg">'
    model = build_report_model(
        run_id="run-item-backdrop",
        items=[item],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert 'class="page-backdrop"' not in card
    assert 'src="https://example.com/item-art.jpg"' not in card
    assert 'class="composition-backdrop is-hero-fallback"' not in card
    assert 'class="editorial-hero-media no-image"' in card
    assert 'class="editorial-hero-copy"' in card
    assert ".editorial-hero { position: absolute; left: 0; right: 0; top: 72px; height: 380px" in card
    assert "background: transparent" in card
    assert "inset: 0; width: 100%; height: 100%; display: block; object-fit: cover" in card
    assert "object-position: 50% center" in card
    assert "color-mix(in srgb, var(--paper) 84%, transparent) 0%" in card
    assert "color-mix(in srgb, var(--paper) 12%, transparent) 100%" in card


def test_generated_concept_art_is_the_only_item_hero_image():
    item = _item("concept", 9)
    item["content"] = '<img src="https://example.com/source.jpg">'
    model = build_report_model(
        run_id="run-concept-hero",
        items=[item],
        meta={"raw_count": 1},
    )
    model["items"][0]["concept_image_url"] = "data:image/png;base64,CONCEPT"

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert card.count("data:image/png;base64,CONCEPT") == 1
    assert "https://example.com/source.jpg" not in card
    assert 'class="editorial-hero-media"' in card
    assert 'class="editorial-hero-media no-image"' not in card


def test_new_editorial_card_uses_agent_owned_display_copy():
    item = _item("headings", 9)
    blocks = item["processing"]["artifacts"]["zh"]["blocks"]
    for block in blocks:
        if block["id"] == "what_happened":
            block["title"] = "每一次看清都会暴露自己"
            block["content"] = "每一次观察都会把观察者暴露给对方。"
        elif block["id"] == "fresh_relationship":
            block["title"] = "感知正在改写局势"
            block["content"] = "感知不再发生在局势之外，它本身就在改变局势。"
        elif block["id"] == "systems_question":
            block["title"] = "熟练之后还剩下什么"
            block["content"] = "当每个人都适应了暴露规则，系统还会制造什么？"

    model = build_report_model(
        run_id="run-display-headings",
        items=[item],
        meta={"raw_count": 1},
    )
    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert "每一次观察都会把观察者暴露给对方。" in card
    assert "每一次看清都会暴露自己" in card
    assert "感知正在改写局势" in card
    assert "感知不再发生在局势之外，它本身就在改变局势。" in card
    assert "熟练之后还剩下什么" in card
    assert "当每个人都适应了暴露规则，系统还会制造什么？" in card
    assert 'data-agent-copy="event"' in card
    assert 'data-agent-copy="insight"' in card
    assert 'data-agent-copy="systems"' in card
    assert "white-space: normal; overflow: visible" in card


def test_content_topic_classification_overrides_account_category():
    model = build_report_model(
        run_id="run-content-topics",
        items=[
            _item(
                "a",
                9,
                category="动物、生态与自然现象",
                profile="gameplay-mechanics",
            )
        ],
        meta={
            "content_topics": [
                {
                    "id": "gameplay-mechanics",
                    "name": "玩法与机制",
                    "color": "#e84a3c",
                    "order": 10,
                }
            ],
        },
    )

    assert model["items"][0]["category"] == "动物、生态与自然现象"
    assert model["items"][0]["section_id"] == "gameplay-mechanics"
    assert model["items"][0]["section"] == "玩法与机制"
    assert model["items"][0]["color"] == REPORT_THEME["brand"]
    assert "## 玩法与机制" in build_markdown(model)
    assert "## 动物、生态与自然现象" not in build_markdown(model)


def test_item_card_uses_topic_color_only_for_category_identity():
    model = build_report_model(
        run_id="run-topic-color",
        items=[_item("world", 9, profile="world-level")],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert f"border: 1px solid {REPORT_THEME['map_blue']}" in card
    assert f"background: {REPORT_THEME['map_blue']}; color: var(--paper)" in card
    assert f"--accent: {REPORT_THEME['map_blue']}" in card
    assert ".item-page .brand strong { color: var(--brand);" in card


def test_item_card_structure_labels_follow_the_topic_color():
    model = build_report_model(
        run_id="run-semantic-section-colors",
        items=[_item("a", 9, profile="gameplay-mechanics")],
        meta={"raw_count": 1},
    )

    card = "".join(card["html"] for card in build_card_html(model, max_cards=4)[2:4])

    assert (
        f".event-index b {{ color: {REPORT_THEME['brand']}; "
        "font-size: 30px; line-height: 1; }"
    ) in card
    assert f".section-index strong {{ color: {REPORT_THEME['brand']};" in card
    assert f"background: {REPORT_THEME['brand']};" in card
    assert "--event-accent:" not in card
    assert "--insight-accent:" not in card
    assert "--question-accent:" not in card
