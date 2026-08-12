from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
from src.image_generation import (
    CardVisualAgent,
    build_composition_prompt,
    build_concept_prompt,
    build_cover_prompt,
    build_mechanism_prompt,
    generate_concept_images,
    generate_composition_images,
    generate_cover_image,
    generate_mechanism_images,
)


def _item() -> dict:
    return {
        "id": "rss:test:item",
        "title": "季节成为一条可见边界",
        "event_heading": "果园中间有一道季节边界",
        "what_happened": "果园两侧呈现不同季节。",
        "mechanism_steps": ["玩家跨过边界", "季节状态改变", "路线价值翻转"],
        "fresh_relationship": "空间边界同时成为时间边界。",
        "insight_heading": "移动也在推动时间",
        "systems_heading": "熟悉之后还会意外吗",
        "systems_question": "路线被反复学习后，边界还会带来意外吗？",
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


def test_mechanism_prompt_visualizes_the_event_as_a_bottom_storyboard_ribbon() -> None:
    prompt = build_mechanism_prompt(_item())

    assert "makes the source event's process visible" in prompt
    assert "event-process visual agent" in prompt
    assert "how it actually unfolded" in prompt
    assert "objects, materials, environments" in prompt
    assert "hand-painted gouache and watercolor" in prompt
    assert "tactile pigment" in prompt
    assert "five to seven equal vertical panels" in prompt
    assert "lower 50 percent" in prompt
    assert "report will crop" in prompt
    assert "five percent at both the left and right edges" in prompt
    assert "must sit fully inside those margins" in prompt
    assert "Do not render titles, captions" in prompt
    assert "single undivided panorama" in prompt
    assert "deep charcoal-green field" not in prompt
    assert "coral red" not in prompt
    assert "1536x512" not in prompt
    assert "native 1536x512 panoramic artwork" not in prompt
    assert "panoramic crop" not in prompt
    assert "空间边界同时成为时间边界" not in prompt
    assert "玩家跨过边界 -> 季节状态改变 -> 路线价值翻转" not in prompt
    assert "Mechanism chain:" not in prompt


def test_mechanism_prompt_does_not_require_a_written_chain() -> None:
    item = _item()
    item["mechanism_steps"] = []

    prompt = build_mechanism_prompt(item)

    assert "果园两侧呈现不同季节" in prompt
    assert "空间边界同时成为时间边界" not in prompt
    assert "Mechanism chain:" not in prompt
    assert "hand-painted gouache" in prompt
    assert "five to seven readable moments" in prompt
    assert "deep charcoal-green" not in prompt


def test_cover_prompt_gives_ai_freedom_but_keeps_brand_safety() -> None:
    second = _item()
    second["title"] = "城市把影子当作通行证"
    prompt = build_cover_prompt(
        [_item(), second],
        report_date="2026-08-05",
        run_id="run-cover",
        fetched_count=204,
    )

    assert "季节成为一条可见边界" in prompt
    assert "城市把影子当作通行证" in prompt
    assert "independently choose" in prompt
    assert "light or dark atmosphere" in prompt
    assert "No words, letters, numbers" in prompt
    assert "glowing marker dots" in prompt


def test_composition_prompt_gives_image2_all_agent_and_template_context() -> None:
    prompt = build_composition_prompt(_item(), reference_count=2)

    assert "最终视觉编排者" in prompt
    assert "果园中间有一道季节边界" in prompt
    assert "移动也在推动时间" in prompt
    assert "路线被反复学习后" in prompt
    assert "Input image 1 is the hero artwork" in prompt
    assert "2:3" in prompt
    assert "不要生成任何文字" in prompt


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
    response.status_code = 200
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


def test_mechanism_generation_no_longer_requires_text_steps(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    image_bytes = b"\x89PNG\r\n\x1a\nnative-panorama"
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["mechanism_steps"] = []

    result = asyncio.run(generate_mechanism_images([item], tmp_path))

    assert result["generated"] == 1
    assert item["mechanism_image_url"].startswith("data:image/png;base64,")
    request = client.post.await_args
    assert request.args[0].endswith("/images/generations")
    assert request.kwargs["json"]["size"] == "1536x512"
    assert Path(item["mechanism_image_path"]).read_bytes() == image_bytes


def test_mechanism_generation_is_independent_from_the_hero_image(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nhero")
    image_bytes = b"\x89PNG\r\n\x1a\nnative-panorama"
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["concept_image_path"] = str(hero)

    result = asyncio.run(generate_mechanism_images([item], tmp_path / "output"))

    assert result["generated"] == 1
    request = client.post.await_args
    assert request.args[0].endswith("/images/generations")
    assert request.kwargs["json"]["size"] == "1536x512"
    assert "files" not in request.kwargs


def test_card_visual_agent_requests_two_images_for_each_item(
    monkeypatch, tmp_path: Path
) -> None:
    item = _item()
    item["mechanism_steps"] = []

    async def concept(items, output_dir):  # type: ignore[no-untyped-def]
        items[0]["image_url"] = "data:image/png;base64,concept"
        return {"generated": 1}

    async def mechanism(items, output_dir):  # type: ignore[no-untyped-def]
        items[0]["mechanism_image_url"] = "data:image/png;base64,mechanism"
        return {"generated": 1}

    monkeypatch.setattr("src.image_generation.generate_concept_images", concept)
    monkeypatch.setattr("src.image_generation.generate_mechanism_images", mechanism)

    result = asyncio.run(CardVisualAgent().generate([item], tmp_path))

    assert result["concept_images"] == {"generated": 1}
    assert result["mechanism_images"] == {"generated": 1}
    assert result["composition_images"]["enabled"] is False
    assert result["requested_items"] == 1
    assert result["complete_items"] == 1
    assert result["orchestrated_items"] == 0


def test_composition_agent_edits_from_hero_and_mechanism_images(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    hero = tmp_path / "hero.png"
    mechanism = tmp_path / "mechanism.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nhero")
    mechanism.write_bytes(b"\x89PNG\r\n\x1a\nmechanism")
    image_bytes = b"\x89PNG\r\n\x1a\ncomposition"
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["concept_image_path"] = str(hero)
    item["mechanism_image_path"] = str(mechanism)

    result = asyncio.run(generate_composition_images([item], tmp_path / "output"))

    assert result["edited"] == 1
    assert result["fallbacks"] == 0
    assert result["transports"][item["id"]] == "images"
    assert item["composition_image_url"].startswith("data:image/png;base64,")
    request = client.post.await_args
    assert request.args[0].endswith("/images/edits")
    assert len(request.kwargs["files"]) == 2
    assert request.kwargs["data"]["size"] == "1024x1536"


def test_composition_agent_uses_responses_when_images_edit_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("HORIZON_IMAGE_EDIT_TRANSPORT", "auto")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nhero")
    request = httpx.Request("POST", "https://example.test/images/edits")
    failed_http_response = httpx.Response(502, request=request)
    failed_response = MagicMock()
    failed_response.status_code = 502
    failed_response.headers = {}
    failed_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad gateway", request=request, response=failed_http_response
    )
    image_bytes = b"\x89PNG\r\n\x1a\nresponses-composition"
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {
        "output": [
            {
                "type": "image_generation_call",
                "result": base64.b64encode(image_bytes).decode("ascii"),
            }
        ]
    }
    client = AsyncMock()
    client.post.side_effect = [failed_response, success_response]
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["concept_image_path"] = str(hero)

    result = asyncio.run(generate_composition_images([item], tmp_path / "output"))

    assert result["generated"] == 1
    assert result["edited"] == 1
    assert result["fallbacks"] == 0
    assert result["failed"] == 0
    assert result["transports"][item["id"]] == "responses"
    assert client.post.await_count == 2
    responses_request = client.post.await_args_list[1]
    assert responses_request.args[0].endswith("/responses")
    assert responses_request.kwargs["json"]["input"][0]["content"][1][
        "type"
    ] == "input_image"


def test_composition_agent_falls_back_when_provider_rejects_image_edits(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("HORIZON_IMAGE_EDIT_TRANSPORT", "images")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nhero")
    request = httpx.Request("POST", "https://example.test/images/edits")
    failed_http_response = httpx.Response(404, request=request)
    failed_response = MagicMock()
    failed_response.status_code = 404
    failed_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found", request=request, response=failed_http_response
    )
    image_bytes = b"\x89PNG\r\n\x1a\nfallback"
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.side_effect = [failed_response, success_response]
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["concept_image_path"] = str(hero)

    result = asyncio.run(generate_composition_images([item], tmp_path / "output"))

    assert result["generated"] == 1
    assert result["edited"] == 0
    assert result["fallbacks"] == 1
    assert result["failed"] == 0
    assert result["modes"][item["id"]] == "generation_fallback"
    assert client.post.await_count == 2


def test_composition_batch_stops_calling_after_provider_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("HORIZON_IMAGE_CONCURRENCY", "1")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    request = httpx.Request("POST", "https://example.test/images/generations")
    failed_http_response = httpx.Response(404, request=request)
    failed_response = MagicMock()
    failed_response.status_code = 404
    failed_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found", request=request, response=failed_http_response
    )
    client = AsyncMock()
    client.post.return_value = failed_response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    first = _item()
    second = {**_item(), "id": "rss:test:second"}

    result = asyncio.run(
        generate_composition_images([first, second], tmp_path / "output")
    )

    assert result["failed"] == 2
    assert client.post.await_count == 1
    assert "skipped after provider failure" in result["errors"][second["id"]]


def test_composition_error_preserves_edit_and_generation_failures(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("HORIZON_IMAGE_EDIT_TRANSPORT", "images")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    hero = tmp_path / "hero.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nhero")
    edit_request = httpx.Request("POST", "https://example.test/images/edits")
    generation_request = httpx.Request(
        "POST", "https://example.test/images/generations"
    )

    def failed_response(status: int, request: httpx.Request) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.headers = {}
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status), request=request, response=httpx.Response(status, request=request)
        )
        return response

    client = AsyncMock()
    client.post.side_effect = [
        failed_response(502, edit_request),
        failed_response(404, generation_request),
    ]
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    item = _item()
    item["concept_image_path"] = str(hero)

    result = asyncio.run(generate_composition_images([item], tmp_path / "output"))

    assert result["failed"] == 1
    assert "image edit transports failed" in result["errors"][item["id"]]
    assert "generation fallback failed" in result["errors"][item["id"]]


def test_generation_retries_transient_provider_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    monkeypatch.setenv("HORIZON_IMAGE_RETRY_ATTEMPTS", "2")
    image_bytes = b"\x89PNG\r\n\x1a\nretry"

    request = httpx.Request("POST", "https://example.test/images/generations")
    failed_http_response = httpx.Response(502, request=request)
    failed_response = MagicMock()
    failed_response.status_code = 502
    failed_response.headers = {}
    failed_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad gateway", request=request, response=failed_http_response
    )
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.side_effect = [failed_response, success_response]
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)
    sleep = AsyncMock()
    monkeypatch.setattr("src.image_generation.asyncio.sleep", sleep)

    result = asyncio.run(generate_concept_images([_item()], tmp_path))

    assert result["generated"] == 1
    assert result["failed"] == 0
    assert client.post.await_count == 2
    sleep.assert_awaited_once()


def test_cover_generation_writes_portrait_cache_and_reuses_it(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HORIZON_IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY_ENV", "TEST_IMAGE_KEY")
    monkeypatch.setenv("TEST_IMAGE_KEY", "secret")
    monkeypatch.setenv("HORIZON_COVER_IMAGE_SIZE", "1024x1536")
    monkeypatch.setenv("HORIZON_COVER_IMAGE_QUALITY", "medium")
    image_bytes = b"\x89PNG\r\n\x1a\ncover"
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr("src.image_generation.httpx.AsyncClient", lambda **_: client)

    kwargs = {
        "report_date": "2026-08-05",
        "run_id": "run-cover",
        "fetched_count": 204,
    }
    first = asyncio.run(generate_cover_image([_item()], tmp_path, **kwargs))
    second = asyncio.run(generate_cover_image([_item()], tmp_path, **kwargs))

    assert first["generated"] == 1
    assert second["cached"] == 1
    assert first["image_url"].startswith("data:image/png;base64,")
    assert second["image_path"] == first["image_path"]
    assert client.post.await_count == 1
    assert client.post.await_args.kwargs["json"]["size"] == "1024x1536"
    assert client.post.await_args.kwargs["json"]["quality"] == "medium"
