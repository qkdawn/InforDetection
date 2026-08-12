from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from src.feishu import (
    FeishuConfig,
    FeishuReportSender,
    validate_report_artifacts,
)


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "https://example.com"))


def test_config_requires_all_environment_variables(monkeypatch):
    for name in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="FEISHU_APP_ID"):
        FeishuConfig.from_env()


def test_validate_report_artifacts_stays_inside_output_root(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    markdown = root / "report.md"
    markdown.write_text("report", encoding="utf-8")
    card = root / "card.png"
    card.write_bytes(b"png")
    monkeypatch.setenv("HORIZON_REPORT_OUTPUT_DIR", str(root))

    resolved_markdown, cards = validate_report_artifacts(
        {"markdown": str(markdown), "cards": [str(card)]}
    )

    assert resolved_markdown == markdown.resolve()
    assert cards == [card.resolve()]


def test_validate_report_artifacts_accepts_more_than_thirty_cards(
    tmp_path, monkeypatch
):
    root = tmp_path / "output"
    root.mkdir()
    markdown = root / "report.md"
    markdown.write_text("report", encoding="utf-8")
    cards = []
    for index in range(31):
        card = root / f"card-{index}.png"
        card.write_bytes(b"png")
        cards.append(str(card))
    monkeypatch.setenv("HORIZON_REPORT_OUTPUT_DIR", str(root))

    _, resolved_cards = validate_report_artifacts(
        {"markdown": str(markdown), "cards": cards}
    )

    assert len(resolved_cards) == 31


def test_validate_report_artifacts_rejects_external_path(tmp_path, monkeypatch):
    root = tmp_path / "output"
    root.mkdir()
    external = tmp_path / "report.md"
    external.write_text("report", encoding="utf-8")
    monkeypatch.setenv("HORIZON_REPORT_OUTPUT_DIR", str(root))

    with pytest.raises(ValueError, match="outside"):
        validate_report_artifacts({"markdown": str(external), "cards": []})


def test_sender_uploads_summary_card_and_markdown(tmp_path, monkeypatch):
    markdown = tmp_path / "report.md"
    markdown.write_text("report", encoding="utf-8")
    card = tmp_path / "card.png"
    card.write_bytes(b"png")
    client = AsyncMock()
    client.post.side_effect = [
        _response({"code": 0, "tenant_access_token": "token"}),
        _response({"code": 0, "data": {"message_id": "summary-message"}}),
        _response({"code": 0, "data": {"image_key": "image-key"}}),
        _response({"code": 0, "data": {"message_id": "image-message"}}),
        _response({"code": 0, "data": {"file_key": "file-key"}}),
        _response({"code": 0, "data": {"message_id": "file-message"}}),
    ]
    monkeypatch.setattr("src.feishu.asyncio.sleep", AsyncMock())
    sender = FeishuReportSender(
        FeishuConfig("app-id", "app-secret", "chat-id"), client=client
    )

    result = asyncio.run(
        sender.deliver(
            report={"name": "Radar", "date": "2026-08-05", "fetched": 10, "selected": 2},
            markdown=markdown,
            cards=[card],
        )
    )

    assert result["card_count"] == 1
    assert result["image_message_ids"] == ["image-message"]
    assert result["file_message_id"] == "file-message"
    assert client.post.await_count == 6
