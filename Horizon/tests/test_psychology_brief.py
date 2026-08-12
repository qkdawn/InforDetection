from __future__ import annotations

import asyncio
import json

import pytest

from src.psychology_brief import PsychologyBriefGenerator


class FakeClient:
    def __init__(self, responses: list[dict]):
        self.responses = [json.dumps(response, ensure_ascii=False) for response in responses]
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _angles() -> dict:
    labels = ["等待过期", "保留选项", "回避责任", "维持好人形象", "夺回节奏", "害怕敷衍"]
    return {
        "candidates": [
            {
                "label": label,
                "thesis": f"关于{label}的独立判断",
                "hidden_payoff": f"{label}暂时免去一个明确决定",
                "emotional_cost": "决定被留给对方和时间承担",
                "recognition_line": "再等等，也许就不用回了。",
                "new_information": f"指出{label}带来的隐秘收益",
                "overreach_risk": "不能解释所有延迟回复",
            }
            for label in labels
        ]
    }


def _insight() -> dict:
    return {
        "selected_label": "等待过期",
        "psychology_concept": "决策回避",
        "concept_definition": "面对需要明确选择的事情时，先推迟行动来避开当下的不适和责任。",
        "mechanism_steps": ["消息要求明确选择", "推迟回复暂时避开不适", "短期轻松让拖延继续"],
        "boundary": "忙碌、信息不足或事情复杂也会造成迟回，不能据此判断人格或关系态度。",
        "lived_moment": "点开重要消息，输入几句又退出。",
        "visible_behavior": "消息一直被留到晚点再回。",
        "hidden_conflict": "想维持关系，又不愿马上作出明确选择。",
        "hidden_payoff": "只要继续拖着，邀请可能失效，对方可能改口，决定就不必由自己亲口说出。",
        "emotional_cost": "对方承担等待和猜测，自己也一直没有真正离开这件事。",
        "uncomfortable_truth": "有时不是在等更好的说法，是在等这条消息失去时效。",
        "core_thesis": "有些消息被拖着，是因为人希望它自己过期。时间一久，那个难做的决定也许就不用亲口说。",
        "what_it_adds": "从在意导致拖延，推进到拖延如何把决定外包给时间。",
        "counterweight": "这不能解释所有迟回，但拖延不会因此没有代价。",
        "emotional_arc": ["认出拖延", "听见借口", "看见收益", "留下代价"],
        "visual_motif": "停在输入状态的聊天框和逐渐变暗的邀请信息。",
        "rejected_labels": ["害怕敷衍", "关系下一步"],
        "rejected_cliches": ["因为太在意", "怕回复不够好", "害怕关系继续"],
    }


def _script() -> dict:
    return {
        "title": "有些消息，你在等它自己过期",
        "subtitle": "拖延也能替人做决定，只是代价不会消失",
        "mood": "尖锐",
        "pages": [
            {
                "role": "cover",
                "eyebrow": "一直没回",
                "headline": "有些消息，你在等它自己过期",
                "body": "再晚一点，邀约也许作废，对方也许改口。到那时，你就不用亲口说要或不要。",
                "pull_quote": "",
            },
            {
                "role": "scene",
                "eyebrow": "晚点再说",
                "headline": "你把一个决定，改名叫晚点再回",
                "body": "消息还在。你告诉自己只是没想好措辞。可你真正等的，也许是情况先发生变化。",
                "pull_quote": "",
            },
            {
                "role": "turn",
                "eyebrow": "拖延的好处",
                "headline": "时间替你说了那句不愿亲口说的话",
                "body": "拖得够久，拒绝像是自然发生，承诺也可以继续悬着。你保住了选择，也暂时不用成为那个明确表态的人。",
                "pull_quote": "你在等消息过期，也在等责任变轻。",
            },
            {
                "role": "aftertaste",
                "eyebrow": "代价去了哪里",
                "headline": "决定没有消失，只是换了人承担",
                "body": "你少说了一句难说的话。对方多等了一段没有答案的时间。",
                "pull_quote": "",
            },
        ],
        "caption": "有些重要消息迟迟没回，未必只因为不知道怎么说。拖延还有一个不太体面的好处：只要再等等，邀约可能失效，对方可能改口，原本需要你表态的事也许会自己过去。这样看，晚点再回有时是在把决定交给时间。决定没有消失，它只是换了一种方式落到别人身上。",
        "tags": ["数字生活", "消息拖延", "情绪观察", "关系选择"],
    }


def _review() -> dict:
    return {
        "verdict": "pass",
        "scores": {
            "novelty": 9,
            "recognition": 9,
            "honesty": 9,
            "progression": 9,
            "human_voice": 8,
            "specificity": 8,
        },
        "topic_delta": "终稿指出拖延的隐秘收益是把明确决定交给时间完成。",
        "cliche_hits": [],
        "fabricated_details": [],
        "notes": ["四页分别承担观察、借口、收益和代价。"],
        "final_script": _script(),
    }


def test_generator_compares_angles_before_writing_without_research():
    client = FakeClient([_angles(), _insight(), _script(), _review()])
    generator = PsychologyBriefGenerator(client)

    result = asyncio.run(
        generator.generate("为什么越重要的消息，越容易拖着不回？", "聊天软件")
    )

    assert len(result["angles"]["candidates"]) == 6
    assert result["insight"]["hidden_payoff"].startswith("只要继续拖着")
    assert result["review"]["scores"]["novelty"] == 9
    assert result["script"]["pages"][0]["headline"].endswith("自己过期")
    assert len(client.calls) == 4
    assert "sources" not in result
    assert "research" not in json.dumps(result, ensure_ascii=False).lower()


@pytest.mark.parametrize("topic", ["短", "x" * 201])
def test_generator_validates_topic_length(topic):
    generator = PsychologyBriefGenerator(FakeClient([]))

    with pytest.raises(ValueError, match="4-200"):
        asyncio.run(generator.generate(topic))
