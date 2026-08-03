from __future__ import annotations

from src.reporting import build_card_html, build_markdown, build_report_model


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
                            "content": f"发生过程 {item_id}",
                        },
                        {
                            "id": "fresh_relationship",
                            "content": f"新鲜关系 {item_id}",
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
    assert "**真正新鲜的关系是什么：** 新鲜关系 a" in markdown
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
    assert cards[-1]["slug"] == "method"
    assert cards[2]["slug"] == "item-01"
    assert cards[3]["slug"] == "item-02"
    assert "发生了什么" in cards[2]["html"]
    assert "真正新鲜的关系是什么" in cards[2]["html"]
    assert "它可能启发哪一类游戏问题" in cards[2]["html"]
    assert "为什么可玩" not in cards[2]["html"]
    assert all("1080px" in card["html"] and "1440px" in card["html"] for card in cards)


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
