from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.image_generation import build_concept_prompt, generate_concept_images


def _item() -> dict:
    return {
        "id": "rss:test:item",
        "title": "季节成为一条可见边界",
        "what_happened": "果园两侧呈现不同季节。",
        "fresh_relationship": "空间边界同时成为时间边界。",
        "game_question": "玩家如何通过移动感知时间？",
        "image_url": None,
    }


def test_concept_prompt_uses_all_three_report_blocks() -> None:
    prompt = build_concept_prompt(_item())

    assert "果园两侧呈现不同季节" in prompt
    assert "空间边界同时成为时间边界" in prompt
    assert "玩家如何通过移动感知时间" in prompt
    assert "gouache" in prompt
    assert "game designer's visual development sketch" in prompt
    assert "watermarks" in prompt


def test_disabled_generation_keeps_item_unchanged(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "false")
    item = _item()

    result = asyncio.run(generate_concept_images([item], tmp_path))

    assert result["enabled"] is False
    assert item["image_url"] is None


def test_generation_writes_cache_and_reuses_it(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    image_bytes = b"\x89PNG\r\n\x1a\nmock"
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)

    first_item = _item()
    first = asyncio.run(generate_concept_images([first_item], tmp_path))
    second_item = _item()
    second = asyncio.run(generate_concept_images([second_item], tmp_path))

    assert first["generated"] == 1
    assert second["cached"] == 1
    assert first_item["image_url"].startswith("data:image/png;base64,")
    assert second_item["image_url"].startswith("data:image/png;base64,")
    assert client.post.await_count == 1
