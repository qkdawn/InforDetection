from __future__ import annotations

import json
from pathlib import Path


def test_single_link_replay_workflow_has_complete_post_fetch_chain() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "n8n"
        / "workflows"
        / "horizon-single-link-replay.json"
    )
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    expected_urls = {
        "复用历史原始材料": "http://horizon-api:8080/replay",
        "重新归类并评分": "http://horizon-api:8080/score",
        "按生产规则筛选": "http://horizon-api:8080/filter",
        "补查关键事实": "http://horizon-api:8080/research",
        "生成编辑稿件": "http://horizon-api:8080/enrich",
        "渲染真实报告": "http://horizon-api:8080/report",
    }
    assert {
        name: nodes[name]["parameters"]["url"] for name in expected_urls
    } == expected_urls
    assert all("/fetch" not in url for url in expected_urls.values())
    assert workflow["active"] is False


def test_single_link_replay_workflow_exposes_ai_context() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "n8n"
        / "workflows"
        / "horizon-single-link-replay.json"
    )
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}
    code = nodes["整理后续 AI 上下文"]["parameters"]["jsCode"]

    assert "ai_context" in code
    assert "trace" in code
    assert "research" in code
    assert "enrichment" in code
    assert "image_generation" in code
    assert "report.report" in code
