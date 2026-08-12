from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "workflows" / "psychology-brief.json"


def test_psychology_workflow_uses_psychology_explainer_stages_only():
    payload = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in payload["nodes"]}
    expected_chain = [
        "保存心理选题",
        "生成6种隐藏解释",
        "精选陌生但准确的角度",
        "编写4页科普分镜",
        "主编质检并重写",
        "渲染4页小红书卡片",
        "推送科普卡片到飞书",
        "返回交付结果",
    ]

    for current, following in zip(expected_chain, expected_chain[1:]):
        connection = payload["connections"][current]["main"][0][0]
        assert connection["node"] == following

    assert nodes["保存心理选题"]["parameters"]["url"].endswith("/psychology/topic")
    assert nodes["生成6种隐藏解释"]["parameters"]["url"].endswith("/psychology/angles")
    assert nodes["精选陌生但准确的角度"]["parameters"]["url"].endswith("/psychology/insight")
    assert nodes["编写4页科普分镜"]["parameters"]["url"].endswith("/psychology/script")
    assert nodes["主编质检并重写"]["parameters"]["url"].endswith("/psychology/review")
    assert nodes["渲染4页小红书卡片"]["parameters"]["url"].endswith("/psychology/render")
    assert nodes["推送科普卡片到飞书"]["parameters"]["url"].endswith("/feishu")
    workflow_text = json.dumps(payload, ensure_ascii=False)
    assert "/psychology/research" not in workflow_text
    assert "搜索" not in workflow_text
