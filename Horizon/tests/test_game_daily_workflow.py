from __future__ import annotations

import json
from pathlib import Path


def test_daily_workflow_uses_research_evaluate_select_enrich_chain() -> None:
    path = Path(__file__).resolve().parents[2] / "n8n" / "workflows" / "game-tech-daily.json"
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert nodes["统一整理候选价值"]["parameters"]["url"].endswith("/evaluate")
    assert nodes["AI终审选择10条"]["parameters"]["url"].endswith("/select")
    assert "threshold: 7.000001" in nodes["板块内筛选去重"]["parameters"]["body"]
    assert "apply_balance: false" in nodes["板块内筛选去重"]["parameters"]["body"]
    assert "limit: 10" in nodes["AI终审选择10条"]["parameters"]["body"]
    assert "max_cards: 12" in nodes["生成创意雷达报告"]["parameters"]["body"]

    assert workflow["connections"]["补查会改变判断的事实"]["main"][0][0]["node"] == "统一整理候选价值"
    assert workflow["connections"]["统一整理候选价值"]["main"][0][0]["node"] == "AI终审选择10条"
    assert workflow["connections"]["AI终审选择10条"]["main"][0][0]["node"] == "游戏设计编辑首次成稿"
