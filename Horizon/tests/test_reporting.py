from __future__ import annotations

from src.reporting import (
    BODY_FONT_FAMILY,
    COVER_ACCENT,
    PRODUCT_COLOR,
    REPORT_THEME,
    TITLE_FONT_FAMILY,
    build_card_html,
    build_markdown,
    build_report_model,
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


def test_card_deck_respects_limit_without_truncating_report_model():
    model = build_report_model(
        run_id="run-test",
        items=[_item(str(index), 10 - index / 10) for index in range(20)],
        meta={"raw_count": 20},
    )
    cards = build_card_html(model, max_cards=12)

    assert len(model["items"]) == 20
    assert len(cards) == 12
    assert cards[0]["slug"] == "cover"
    assert cards[1]["slug"] == "directory"
    assert cards[2]["slug"] == "item-01"
    assert cards[-1]["slug"] == "item-10"
    assert "值得偷走的" in cards[0]["html"]
    assert "从真实世界" in cards[0]["html"]
    assert "长出游戏" in cards[0]["html"]
    assert "从今日 20 条现实材料里" in cards[0]["html"]
    assert "cover-count-panel" in cards[0]["html"]
    assert "cover-taxonomy" in cards[0]["html"]
    assert "中文标题 0" in cards[1]["html"]
    assert "中文标题 19" in cards[1]["html"]
    assert "事件" in cards[2]["html"]
    assert "设计启示" in cards[2]["html"]
    assert "系统追问" in cards[2]["html"]
    assert "事件过程" in cards[2]["html"]
    assert '<div class="event-index">' in cards[2]["html"]
    assert '<div class="event-index">\n              <b>事件</b>' in cards[2]["html"]
    assert "<strong>00</strong>" not in cards[2]["html"]
    assert "insight-symbol" not in cards[2]["html"]
    assert '<i></i><b>事件过程</b></div>' in cards[2]["html"]
    assert "MECHANIC<br>BREAKDOWN" not in cards[2]["html"]
    assert '<i></i><b>设计启示</b></div>' in cards[2]["html"]
    assert '<i></i><b>系统追问</b></div>' in cards[2]["html"]
    assert "DESIGN<br>IMPLICATIONS" not in cards[2]["html"]
    assert "EXTENDED<br>THOUGHT" not in cards[2]["html"]
    assert 'class="panel-kicker"' not in cards[2]["html"]
    assert "为什么成立" not in cards[2]["html"]
    assert "一句话洞察" not in cards[2]["html"]
    assert "这件事改写了什么" not in cards[2]["html"]
    assert "延伸思考" not in cards[2]["html"]
    assert "系统继续变化会发生什么 0？" in cards[2]["html"]
    assert "mechanism-board" in cards[2]["html"]
    assert "事件标题 0" in cards[2]["html"]
    assert "发生过程 0" in cards[2]["html"]
    assert "设计标题 0" in cards[2]["html"]
    assert "新鲜关系 0" in cards[2]["html"]
    assert "系统标题 0" in cards[2]["html"]
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
    assert 'class="page item-page"' in cards[2]["html"]
    assert f'--paper: {REPORT_THEME["paper"]}' in cards[0]["html"]
    assert ".cover-page { background: var(--paper)" in cards[0]["html"]
    assert ".item-page { background: var(--paper)" in cards[2]["html"]
    assert (
        ".cover-count-panel { position: absolute; right: 54px; "
        "top: 100px; width: 316px; height: 316px; padding: 38px 28px 24px; "
        f"background: {COVER_ACCENT};"
    ) in cards[0]["html"]
    assert f".directory-row strong {{ color: {COVER_ACCENT};" in cards[1]["html"]
    assert PRODUCT_COLOR != COVER_ACCENT
    assert (
        f".editorial-tag {{ display: inline-flex; max-width: 240px; padding: 8px 12px; border: 1px solid {PRODUCT_COLOR};"
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


def test_card_displays_the_native_21_9_mechanism_visual_without_cropping():
    model = build_report_model(
        run_id="run-mechanism-art",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["mechanism_image_url"] = "data:image/png;base64,MECHANISM-ART"

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert card.count('class="mechanism-strip"') == 1
    assert card.count("data:image/png;base64,MECHANISM-ART") == 1
    assert "object-fit: contain" in card
    assert "object-position: 50% 50%" in card
    assert ".mechanism-board { position: absolute; left: 36px; right: 36px; top: 662px; height: 398px" in card
    assert ".mechanism-strip { position: absolute; inset: 12px 14px" in card
    assert "border-radius: 4px" in card
    assert 'class="media-fit"' in card
    assert 'class="mechanism-fallback"' not in card


def test_item_card_uses_a_warm_paper_background_palette():
    model = build_report_model(
        run_id="run-warm-paper-card",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert f'--paper: {REPORT_THEME["paper"]}' in card
    assert f'--paper-soft: {REPORT_THEME["paper_soft"]}' in card
    assert f'--ink: {REPORT_THEME["ink"]}' in card
    assert f'--muted: {REPORT_THEME["muted"]}' in card
    assert f'--line: {REPORT_THEME["line"]}' in card
    assert ".item-page { background: var(--paper)" in card
    assert ".editorial-title" in card
    assert "color: var(--ink)" in card
    assert ".event-strip {" in card
    assert "background: var(--paper-soft)" in card
    assert ".bottom-board {" in card


def test_item_card_body_type_is_readable_at_thumbnail_size():
    model = build_report_model(
        run_id="run-readable-type",
        items=[_item("type", 9)],
        meta={"raw_count": 1},
    )

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert "calc(25px * var(--copy-scale))/1.3" in card
    assert "calc(22px * var(--copy-scale))/1.32" in card
    assert "calc(17px * var(--copy-scale))/1.58" in card
    assert "calc(17px * var(--copy-scale))/1.62" in card
    assert "size > 42" in card


def test_event_copy_is_vertically_centered_beside_its_heading():
    model = build_report_model(
        run_id="run-centered-event-copy",
        items=[_item("event", 9)],
        meta={"raw_count": 1},
    )

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert (
        ".event-body { --copy-scale: 1; height: 178px; padding: 0 30px; "
        "display: flex; align-items: center; overflow: hidden; }"
    ) in card


def test_report_embeds_reusable_display_and_body_font_roles():
    model = build_report_model(
        run_id="run-round-title-font",
        items=[_item("type", 9)],
        meta={"raw_count": 1},
    )

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert f'font-family: "{TITLE_FONT_FAMILY}"' in card
    assert f'font-family: "{BODY_FONT_FAMILY}"' in card
    assert card.count("data:font/woff2;base64,") == 2
    assert f'--font-display: "{TITLE_FONT_FAMILY}"' in card
    assert f'--font-body: "{BODY_FONT_FAMILY}"' in card
    assert "font: 400 60px/1.12 var(--font-display)" in card
    assert (
        "font: 700 calc(17px * var(--copy-scale))/1.58 var(--font-body)"
        in card
    )
    assert "font: 500 14px var(--font-mono)" in card


def test_report_css_contains_no_legacy_dark_green_theme_tokens():
    model = build_report_model(
        run_id="run-paper-only-theme",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )

    html = "".join(card["html"] for card in build_card_html(model, max_cards=3))

    for token in (
        "#03150f",
        "#07140f",
        "#071b14",
        "#0b2a20",
        "#0d1814",
        "#101512",
        "#17382f",
        "#214a3f",
        "#244c3d",
        "#315c50",
        "rgba(3, 21, 15",
        "rgba(23, 56, 47",
    ):
        assert token not in html


def test_card_ignores_legacy_composition_image_layer():
    model = build_report_model(
        run_id="run-composition-art",
        items=[_item("a", 9)],
        meta={"raw_count": 1},
    )
    model["items"][0]["composition_image_url"] = "data:image/png;base64,COMPOSITION-ART"

    card = build_card_html(model, max_cards=3)[2]["html"]

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

    card = build_card_html(model, max_cards=3)[2]["html"]

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

    card = build_card_html(model, max_cards=3)[2]["html"]

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
    card = build_card_html(model, max_cards=3)[2]["html"]

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

    card = build_card_html(model, max_cards=3)[2]["html"]

    assert 'class="page-backdrop"' not in card
    assert 'src="https://example.com/item-art.jpg"' not in card
    assert 'class="composition-backdrop is-hero-fallback"' not in card
    assert 'class="editorial-hero-media no-image"' in card
    assert 'class="editorial-hero-copy"' in card
    assert "transparent 80%" in card
    assert "object-position: right center" in card


def test_generated_concept_art_is_the_only_item_hero_image():
    item = _item("concept", 9)
    item["content"] = '<img src="https://example.com/source.jpg">'
    model = build_report_model(
        run_id="run-concept-hero",
        items=[item],
        meta={"raw_count": 1},
    )
    model["items"][0]["concept_image_url"] = "data:image/png;base64,CONCEPT"

    card = build_card_html(model, max_cards=3)[2]["html"]

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
    card = build_card_html(model, max_cards=3)[2]["html"]

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
    assert "## 玩法与机制" in build_markdown(model)
    assert "## 动物、生态与自然现象" not in build_markdown(model)
