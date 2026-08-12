from __future__ import annotations

from src.psychology_reporting import (
    _page_art_prompt,
    build_psychology_cards,
    build_psychology_markdown,
)


def _payload() -> dict:
    return {
        "topic": "为什么越重要的消息越容易拖着不回？",
        "insight": {
            "psychology_concept": "决策回避",
            "concept_definition": "面对需要明确选择的事情时，先推迟行动来避开当下的不适。",
            "boundary": "一次迟回不能用于判断人格或关系态度。",
            "lived_moment": "消息亮起，字写了又删。",
            "visible_behavior": "看见却没有回复。",
            "hidden_conflict": "想认真回应，又怕对话继续。",
            "core_thesis": "拖着的不是一句回复，而是回复之后会继续发生的关系。",
            "emotional_arc": ["认出", "刺痛", "反转", "余味"],
            "visual_motif": "冷掉的水和亮着的手机。",
        },
        "review": {
            "verdict": "revised",
            "scores": {"hook": 9, "resonance": 9, "insight": 8, "rhythm": 9, "human_voice": 9},
            "notes": ["删掉了一页重复解释。"],
        },
        "script": {
            "title": "你不是不想回，你是不想让对话继续",
            "subtitle": "越重要的消息，越像一扇推开就关不上的门",
            "mood": "酸涩",
            "pages": [
                {"role": "cover", "eyebrow": "屏幕里的我们", "headline": "你不是不想回，你是不想让对话继续", "body": "越重要的消息，越像一扇推开就关不上的门。", "pull_quote": ""},
                {"role": "scene", "eyebrow": "那个瞬间", "headline": "字都想好了，手却又退出了对话框", "body": "你知道一旦发出去，解释、表态和回应都会跟着来。", "pull_quote": "你躲开的不是输入框。"},
                {"role": "turn", "eyebrow": "真正难回的", "headline": "被拖延的不是打字，是关系要继续发生", "body": "所谓晚点认真回，常常只是把压力留给下一次打开。", "pull_quote": "沉默，是暂时不用表态。"},
                {"role": "aftertaste", "eyebrow": "留一句给自己", "headline": "下次又想退出时，看看你到底在躲什么", "body": "也许不是不知道怎么说，而是不想面对说完以后会去向哪里。", "pull_quote": "你在躲措辞，还是在躲继续？"},
            ],
            "caption": "有些消息不是难在不知道怎么回，而是你太清楚回复之后会发生什么。于是你告诉自己晚点认真回，却把那份压力完整地留给下一次打开。这里不替任何沉默找借口，只想把那个退出对话框的瞬间看清楚。",
            "tags": ["数字生活", "聊天日常", "情绪观察"],
        },
    }


def test_psychology_deck_is_compact_editorial_story_without_sources():
    cards = build_psychology_cards(_payload(), cover_url="data:image/png;base64,COVER")

    assert [card["slug"] for card in cards] == ["cover", "scene", "turn", "aftertaste"]
    assert all("1080px" in card["html"] and "1440px" in card["html"] for card in cards)
    assert "data:image/png;base64,COVER" in cards[0]["html"]
    combined = " ".join(card["html"] for card in cards)
    assert "研究怎么说" not in combined
    assert "证据" not in combined
    assert "来源" not in combined


def test_psychology_deck_accepts_distinct_art_for_every_page():
    page_images = {
        role: f"data:image/png;base64,{role.upper()}"
        for role in ("cover", "scene", "turn", "aftertaste")
    }

    cards = build_psychology_cards(_payload(), page_images=page_images)

    for card in cards:
        assert page_images[card["slug"]] in card["html"]


def test_page_art_prompts_share_paper_bible_but_change_composition_by_role():
    payload = _payload()
    prompts = {
        page["role"]: _page_art_prompt(payload, page)
        for page in payload["script"]["pages"]
    }

    assert all("hand-cut paper collage" in prompt for prompt in prompts.values())
    assert all("No words, letters, numbers" in prompt for prompt in prompts.values())
    assert "Portrait 2:3" in prompts["cover"]
    assert all("Wide 3:2" in prompts[role] for role in ("scene", "turn", "aftertaste"))
    assert len(set(prompts.values())) == 4


def test_psychology_markdown_keeps_caption_and_editor_review():
    markdown = build_psychology_markdown(_payload())

    assert "## 小红书文案" in markdown
    assert "## 主编检查" in markdown
    assert "#数字生活" in markdown
    assert "检索记录" not in markdown
    assert "不用于判断人格或进行心理诊断" in markdown
