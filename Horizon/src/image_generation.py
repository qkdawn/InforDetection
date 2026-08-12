"""Generate and cache concept images for report cards."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
logger = logging.getLogger(__name__)
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ConceptImageConfig:
    enabled: bool
    base_url: str
    api_key_env: str
    model: str
    size: str
    cover_size: str
    mechanism_size: str
    composition_size: str
    quality: str
    cover_quality: str
    composition_quality: str
    composition_enabled: bool
    concurrency: int
    timeout_seconds: float
    retry_attempts: int
    edit_retry_attempts: int
    edit_transport: str
    retry_backoff_seconds: float
    trust_env: bool

    @classmethod
    def from_env(cls) -> "ConceptImageConfig":
        try:
            concurrency = int(os.getenv("HORIZON_IMAGE_CONCURRENCY", "2"))
        except ValueError:
            concurrency = 2
        try:
            timeout_seconds = float(os.getenv("HORIZON_IMAGE_TIMEOUT_SECONDS", "240"))
        except ValueError:
            timeout_seconds = 240.0
        try:
            retry_attempts = int(os.getenv("HORIZON_IMAGE_RETRY_ATTEMPTS", "4"))
        except ValueError:
            retry_attempts = 4
        try:
            retry_backoff_seconds = float(
                os.getenv("HORIZON_IMAGE_RETRY_BACKOFF_SECONDS", "4")
            )
        except ValueError:
            retry_backoff_seconds = 4.0
        try:
            edit_retry_attempts = int(
                os.getenv("HORIZON_IMAGE_EDIT_RETRY_ATTEMPTS", "1")
            )
        except ValueError:
            edit_retry_attempts = 1
        edit_transport = os.getenv(
            "HORIZON_IMAGE_EDIT_TRANSPORT", "auto"
        ).strip().lower()
        if edit_transport not in {"auto", "images", "responses"}:
            edit_transport = "auto"
        return cls(
            enabled=os.getenv("HORIZON_IMAGE_GENERATION_ENABLED", "false").lower()
            in _TRUTHY,
            base_url=os.getenv(
                "HORIZON_IMAGE_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            api_key_env=os.getenv("HORIZON_IMAGE_API_KEY_ENV", "OPENAI_API_KEY"),
            model=os.getenv("HORIZON_IMAGE_MODEL", "gpt-image-2"),
            size=os.getenv("HORIZON_IMAGE_SIZE", "1536x1024"),
            cover_size=os.getenv("HORIZON_COVER_IMAGE_SIZE", "1024x1536"),
            mechanism_size=os.getenv("HORIZON_MECHANISM_IMAGE_SIZE", "1536x512"),
            composition_size=os.getenv("HORIZON_COMPOSITION_IMAGE_SIZE", "1024x1536"),
            quality=os.getenv("HORIZON_IMAGE_QUALITY", "low"),
            cover_quality=os.getenv("HORIZON_COVER_IMAGE_QUALITY", "medium"),
            composition_quality=os.getenv("HORIZON_COMPOSITION_IMAGE_QUALITY", "low"),
            composition_enabled=os.getenv(
                "HORIZON_COMPOSITION_IMAGE_ENABLED", "true"
            ).lower()
            in _TRUTHY,
            concurrency=max(1, min(concurrency, 4)),
            timeout_seconds=max(30.0, min(timeout_seconds, 600.0)),
            retry_attempts=max(1, min(retry_attempts, 6)),
            edit_retry_attempts=max(1, min(edit_retry_attempts, 3)),
            edit_transport=edit_transport,
            retry_backoff_seconds=max(0.5, min(retry_backoff_seconds, 60.0)),
            trust_env=os.getenv("HORIZON_IMAGE_TRUST_ENV", "true").lower() in _TRUTHY,
        )


@dataclass
class ConceptImageBatchResult:
    enabled: bool
    model: str
    generated: int = 0
    cached: int = 0
    failed: int = 0
    images: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "generated": self.generated,
            "cached": self.cached,
            "failed": self.failed,
            "images": self.images,
            "errors": self.errors,
        }


@dataclass
class CompositionImageBatchResult(ConceptImageBatchResult):
    edited: int = 0
    fallbacks: int = 0
    modes: dict[str, str] = field(default_factory=dict)
    transports: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "edited": self.edited,
            "fallbacks": self.fallbacks,
            "modes": self.modes,
            "transports": self.transports,
        }


def _compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def build_cover_prompt(
    items: list[dict[str, Any]],
    *,
    report_date: str,
    run_id: str,
    fetched_count: int,
) -> str:
    """Give the image model broad art direction grounded in the day's signals."""
    signals = []
    for index, item in enumerate(items[:6], start=1):
        signals.append(
            " | ".join(
                [
                    f"{index:02d}. {_compact(item.get('title'), 72)}",
                    f"event: {_compact(item.get('what_happened'))}",
                    f"relationship: {_compact(item.get('fresh_relationship'))}",
                ]
            )
        )
    signal_block = "\n".join(signals) or "No strong signal was selected today."
    variation_key = hashlib.sha256(f"{report_date}:{run_id}".encode()).hexdigest()[:10]
    return "\n".join(
        [
            "Use case: stylized-concept",
            "Asset type: text-free portrait master artwork for a daily game-inspiration cover",
            (
                "Primary request: act as the visual director. Read the daily signals below, "
                "choose the strongest shared theme or most provocative tension, then invent "
                "one beautiful XR fantasy world that expresses it indirectly. Do not make a "
                "collage of every story and do not illustrate the wording literally."
            ),
            f"Editorial context: {report_date}; {fetched_count} source materials; variation key {variation_key}.",
            "Daily signals:",
            signal_block,
            (
                "Creative freedom: independently choose the world, dominant motif, viewpoint, "
                "scale, weather, era, light or dark atmosphere, and degree of archival collage. "
                "A pale field-notes mood, a luminous XR dream, a dark mythic panorama, or another "
                "coherent interpretation are all valid. Surprise is welcome when it remains beautiful."
            ),
            (
                "Visual DNA, not a rigid recipe: authored painterly worldbuilding with tactile "
                "paper, pigment, ink, or weathered print character; immense spatial depth; a human "
                "trace may appear for scale; deep forest green, warm ivory, mineral blue, and "
                "weathered yellow may recur but the image may choose its own dominant climate."
            ),
            (
                "Composition/framing: portrait 2:3. Build a continuous world rather than framed "
                "panels. Let landscape, architecture, cloud, or mist extend upward naturally. The "
                "upper third will blend into a paper-colored typography layer, so keep its tonal "
                "rhythm elegant without forcing empty space. Preserve a strong readable world in "
                "the middle and lower half."
            ),
            (
                "Constraints: image only. No words, letters, numbers, logos, watermarks, UI, HUD, "
                "captions, interface icons, glowing marker dots, coordinate ticks, or explanatory diagrams."
            ),
            (
                "Avoid: generic neon sci-fi, glossy game-key-art cliches, direct headset imagery, "
                "split-screen storytelling, and arbitrary decorative linework."
            ),
        ]
    )


def build_concept_prompt(item: dict[str, Any]) -> str:
    """Build a source-grounded visual prompt for one report item."""
    return "\n".join(
        [
            "Use case: stylized-concept",
            "Asset type: wide hero image for a game inspiration editorial card",
            f"Primary request: visualize the core relationship in '{item.get('title', '')}'.",
            f"Source event: {item.get('what_happened', '')}",
            f"Fresh relationship: {item.get('fresh_relationship', '')}",
            f"Design question: {item.get('game_question', '')}",
            (
                "Style/medium: sophisticated hand-painted environment concept art "
                "using gouache, colored pencil, and sparse ink on textured paper; "
                "visible brushwork, tactile and authored, like a game designer's "
                "visual development sketch rather than a finished movie poster"
            ),
            (
                "Composition/framing: wide 3:2 landscape, one clear off-center focal "
                "relationship, legible spatial or behavioral logic, readable at card "
                "size, with a quieter darker lower or side area for a white title overlay"
            ),
            (
                "Lighting/mood: environmental light shaped through painted color and "
                "edges, atmospheric but restrained"
            ),
            (
                "Constraints: build one coherent, source-grounded scene that makes the "
                "fresh relationship visible instead of illustrating the wording literally"
            ),
            (
                "Avoid: words, letters, captions, logos, watermarks, UI, diagrams, "
                "split-screen labels, generic digital fantasy rendering, neon sci-fi, "
                "cute cartoon styling"
            ),
        ]
    )


def build_mechanism_prompt(item: dict[str, Any]) -> str:
    """Turn the reported event into a source-grounded storyboard ribbon."""
    return "\n".join(
        [
            "Use case: stylized-concept",
            (
                "Asset type: a horizontal editorial storyboard ribbon that makes the "
                "source event's process visible through adjacent moments"
            ),
            f"Editorial subject: {item.get('title', '')}",
            "Event to visualize:",
            _compact(item.get("what_happened"), 420),
            (
                "Role: act as the event-process visual agent. Reconstruct the concrete sequence "
                "inside the report: who or what acts first, what changes, what is revealed or "
                "withheld, and what state exists at the end. Divide that sequence into five to "
                "seven readable moments arranged from left to right."
            ),
            (
                "Truth and imagination: keep the people, objects, materials, environments, and "
                "actions recognizable and grounded in the source. Follow the event's own logic and "
                "use consistent characters, objects, weather, and geography across every panel. "
                "Choose the moments, viewpoint, traces, repetition, or material transformation "
                "that best reveal how it actually unfolded."
            ),
            (
                "Composition: make the lower 50 percent of the returned canvas the primary "
                "deliverable: one uninterrupted, very wide strip of five to seven equal vertical "
                "panels separated by fine ink rules. Each panel shows one distinct action or state, "
                "with a clear left-to-right rhythm like an illustrated field notebook. Keep all "
                "essential figures and actions inside this lower strip because the report will crop "
                "and display only that area. The upper canvas may extend the same environment but "
                "must contain no essential step. Leave a continuous warm-paper safety margin of "
                "about five percent at both the left and right edges. The first and final panel "
                "borders, figures, and objects must sit fully inside those margins rather than "
                "touching or continuing beyond the canvas edge."
            ),
            (
                "Art direction: concise editorial game-design illustration on warm weathered paper, "
                "hand-painted gouache and watercolor with sparse graphite or ink, strong silhouettes, "
                "tactile pigment, selective detail, and visibly authored marks. Let the subject establish "
                "its own restrained color world while keeping every panel visually coherent."
            ),
            (
                "Constraints: pure visual storytelling. Do not render titles, captions, prose, labels, "
                "letters, numbers, logos, watermarks, UI, charts, or explanatory typography. Do not "
                "make a single undivided panorama, a comic page with speech balloons, or a grid with "
                "multiple rows."
            ),
            (
                "Deliver a publication-ready image whose cropped lower storyboard ribbon remains "
                "complete and understandable on its own."
            ),
        ]
    )


def _visual_composition_direction() -> str:
    configured = os.getenv("HORIZON_VISUAL_COMPOSITION_PROMPT", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(__file__).resolve().parents[1]
        / "profiles"
        / "game-tech-daily"
        / "visual-composition.md",
        Path("profiles/game-tech-daily/visual-composition.md"),
    ]
    for path in candidates:
        if path and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return (
        "Create a text-free portrait atmosphere plate for the supplied editorial "
        "template. Preserve quiet areas for typography and use one restrained accent."
    )


def build_composition_prompt(item: dict[str, Any], *, reference_count: int = 0) -> str:
    """Give the final visual agent the complete editorial and template context."""
    references = (
        "Input image 1 is the hero artwork and input image 2 is the mechanism artwork."
        if reference_count >= 2
        else "Use the supplied reference image as visual evidence."
        if reference_count == 1
        else "No reference image is available; infer the visual atmosphere from the text."
    )
    return "\n".join(
        [
            "Use case: final-editorial-composition",
            "Asset type: text-free portrait atmosphere plate behind a fixed report template",
            "# Visual composition direction",
            _visual_composition_direction(),
            "# Editorial context",
            f"Title: {_compact(item.get('title'), 100)}",
            f"Event title: {_compact(item.get('event_heading'), 120)}",
            f"Event: {_compact(item.get('what_happened'), 520)}",
            f"Design insight title: {_compact(item.get('insight_heading'), 120)}",
            f"Core discovery: {_compact(item.get('fresh_relationship'), 520)}",
            f"Systems title: {_compact(item.get('systems_heading'), 120)}",
            f"Systems question: {_compact(item.get('systems_question'), 300)}",
            "# Reference images",
            references,
        ]
    )


def _cache_path(
    output_dir: Path, item: dict[str, Any], config: ConceptImageConfig
) -> Path:
    payload = {
        "id": item.get("id"),
        "prompt": build_concept_prompt(item),
        "model": config.model,
        "size": config.size,
        "quality": config.quality,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return output_dir / f"{digest}.png"


def _mechanism_cache_path(
    output_dir: Path, item: dict[str, Any], config: ConceptImageConfig
) -> Path:
    payload = {
        "id": item.get("id"),
        "prompt": build_mechanism_prompt(item),
        "model": config.model,
        "size": config.mechanism_size,
        "quality": config.quality,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return output_dir / f"mechanism-{digest}.png"


def _data_uri(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _reference_image_bytes(item: dict[str, Any]) -> list[tuple[str, bytes, str]]:
    references: list[tuple[str, bytes, str]] = []
    for name, path_key, url_key in (
        ("hero", "concept_image_path", "image_url"),
        ("mechanism", "mechanism_image_path", "mechanism_image_url"),
    ):
        data = b""
        raw_path = str(item.get(path_key) or "").strip()
        if raw_path:
            path = Path(raw_path)
            if path.is_file():
                data = path.read_bytes()
        if not data:
            raw_url = str(item.get(url_key) or "").strip()
            if raw_url.startswith("data:") and "," in raw_url:
                try:
                    data = base64.b64decode(raw_url.split(",", 1)[1])
                except ValueError:
                    data = b""
        if data:
            mime = _image_mime(data)
            suffix = {
                "image/png": "png",
                "image/jpeg": "jpg",
                "image/webp": "webp",
            }.get(mime, "bin")
            references.append((f"{name}.{suffix}", data, mime))
    return references


def _composition_cache_path(
    output_dir: Path,
    item: dict[str, Any],
    config: ConceptImageConfig,
    references: list[tuple[str, bytes, str]],
) -> Path:
    payload = {
        "id": item.get("id"),
        "prompt": build_composition_prompt(item, reference_count=len(references)),
        "references": [hashlib.sha256(data).hexdigest() for _, data, _ in references],
        "model": config.model,
        "size": config.composition_size,
        "quality": config.composition_quality,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return output_dir / f"composition-{digest}.png"


class _RetryableImageError(RuntimeError):
    """The provider returned a transient or incomplete image response."""


async def _image_bytes_from_payload(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    *,
    response_name: str,
) -> bytes:
    """Read image bytes from Images or Responses compatible payloads."""
    candidates: list[dict[str, Any]] = []
    candidates.extend(row for row in payload.get("data") or [] if isinstance(row, dict))
    for output in payload.get("output") or []:
        if not isinstance(output, dict):
            continue
        candidates.append(output)
        candidates.extend(
            row for row in output.get("content") or [] if isinstance(row, dict)
        )

    for row in candidates:
        encoded = (
            row.get("b64_json")
            or row.get("result")
            or row.get("image_base64")
        )
        if encoded:
            data = base64.b64decode(encoded)
            if data:
                return data
        image_url = row.get("url") or row.get("image_url")
        if image_url:
            image_response = await client.get(image_url)
            image_response.raise_for_status()
            if image_response.content:
                return image_response.content
    raise _RetryableImageError(
        f"{response_name} returned neither image base64 nor url"
    )


def _retry_delay(
    response: httpx.Response | None, config: ConceptImageConfig, attempt: int
) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after", "").strip()
        try:
            return max(0.0, min(float(retry_after), 120.0))
        except ValueError:
            pass
    return min(config.retry_backoff_seconds * (2 ** (attempt - 1)), 120.0)


async def _request_image(
    client: httpx.AsyncClient,
    config: ConceptImageConfig,
    api_key: str,
    prompt: str,
    *,
    size: str | None = None,
    quality: str | None = None,
) -> bytes:
    request = {
        "model": config.model,
        "prompt": prompt,
        "size": size or config.size,
        "quality": quality or config.quality,
        "n": 1,
    }
    last_error: Exception | None = None
    for attempt in range(1, config.retry_attempts + 1):
        response: httpx.Response | None = None
        try:
            response = await client.post(
                f"{config.base_url}/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json=request,
            )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            payload = response.json()
            return await _image_bytes_from_payload(
                client, payload, response_name="image API"
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status != 429 and status < 500:
                raise
            last_error = exc
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            _RetryableImageError,
            ValueError,
        ) as exc:
            last_error = exc

        if attempt >= config.retry_attempts:
            break
        delay = _retry_delay(response, config, attempt)
        logger.warning(
            "Image API attempt %s/%s failed (%s); retrying in %.1fs",
            attempt,
            config.retry_attempts,
            last_error,
            delay,
        )
        await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("image API request failed without an error")


async def _request_images_edit(
    client: httpx.AsyncClient,
    config: ConceptImageConfig,
    api_key: str,
    prompt: str,
    references: list[tuple[str, bytes, str]],
    *,
    size: str,
    quality: str,
) -> bytes:
    """Ask an OpenAI-compatible image endpoint to compose from visual references."""
    files = [("image[]", (filename, data, mime)) for filename, data, mime in references]
    form = {
        "model": config.model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": "1",
    }
    last_error: Exception | None = None
    for attempt in range(1, config.edit_retry_attempts + 1):
        response: httpx.Response | None = None
        try:
            response = await client.post(
                f"{config.base_url}/images/edits",
                headers={"Authorization": f"Bearer {api_key}"},
                data=form,
                files=files,
            )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            payload = response.json()
            return await _image_bytes_from_payload(
                client, payload, response_name="image edit API"
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status != 429 and status < 500:
                raise
            last_error = exc
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            _RetryableImageError,
            ValueError,
        ) as exc:
            last_error = exc

        if attempt >= config.edit_retry_attempts:
            break
        delay = _retry_delay(response, config, attempt)
        logger.warning(
            "Image edit API attempt %s/%s failed (%s); retrying in %.1fs",
            attempt,
            config.edit_retry_attempts,
            last_error,
            delay,
        )
        await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("image edit API request failed without an error")


async def _request_responses_image_edit(
    client: httpx.AsyncClient,
    config: ConceptImageConfig,
    api_key: str,
    prompt: str,
    references: list[tuple[str, bytes, str]],
    *,
    size: str,
    quality: str,
) -> bytes:
    """Use a Responses-compatible image route when Images edits are unavailable."""
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend(
        {"type": "input_image", "image_url": _data_uri(data)}
        for _, data, _ in references
    )
    request = {
        "model": config.model,
        "input": [{"role": "user", "content": content}],
        "size": size,
        "quality": quality,
    }
    response = await client.post(
        f"{config.base_url}/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        json=request,
    )
    response.raise_for_status()
    return await _image_bytes_from_payload(
        client, response.json(), response_name="Responses image API"
    )


async def _request_image_edit(
    client: httpx.AsyncClient,
    config: ConceptImageConfig,
    api_key: str,
    prompt: str,
    references: list[tuple[str, bytes, str]],
    *,
    size: str,
    quality: str,
) -> tuple[bytes, str]:
    """Compose references through the configured provider transport."""
    transports = (
        ("images", "responses")
        if config.edit_transport == "auto"
        else (config.edit_transport,)
    )
    failures: list[str] = []
    last_error: Exception | None = None
    for transport in transports:
        try:
            if transport == "responses":
                data = await _request_responses_image_edit(
                    client,
                    config,
                    api_key,
                    prompt,
                    references,
                    size=size,
                    quality=quality,
                )
            else:
                data = await _request_images_edit(
                    client,
                    config,
                    api_key,
                    prompt,
                    references,
                    size=size,
                    quality=quality,
                )
            return data, transport
        except Exception as exc:
            last_error = exc
            failures.append(f"{transport}: {type(exc).__name__}: {exc}")
            if len(transports) > 1:
                logger.warning("Image edit transport %s failed: %s", transport, exc)

    detail = "; ".join(failures)
    if last_error is not None:
        raise RuntimeError(f"all image edit transports failed ({detail})") from last_error
    raise RuntimeError("no image edit transport was configured")


async def generate_cover_image(
    items: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    report_date: str,
    run_id: str,
    fetched_count: int,
) -> dict[str, Any]:
    """Generate one cached, daily art-directed cover image from multiple signals."""
    config = ConceptImageConfig.from_env()
    prompt = build_cover_prompt(
        items,
        report_date=report_date,
        run_id=run_id,
        fetched_count=fetched_count,
    )
    result: dict[str, Any] = {
        "enabled": config.enabled,
        "model": config.model,
        "generated": 0,
        "cached": 0,
        "failed": 0,
        "image_path": None,
        "image_url": None,
        "prompt": prompt,
        "error": None,
    }
    if not config.enabled or not items:
        return result

    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        result["failed"] = 1
        result["error"] = (
            f"missing image API key environment variable {config.api_key_env}"
        )
        return result

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompt": prompt,
        "model": config.model,
        "size": config.cover_size,
        "quality": config.cover_quality,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    path = target_dir / f"cover-{digest}.png"
    try:
        if path.exists() and path.stat().st_size > 0:
            data = path.read_bytes()
            result["cached"] = 1
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.timeout_seconds),
                trust_env=config.trust_env,
            ) as client:
                data = await _request_image(
                    client,
                    config,
                    api_key,
                    prompt,
                    size=config.cover_size,
                    quality=config.cover_quality,
                )
            path.write_bytes(data)
            result["generated"] = 1
        result["image_path"] = str(path)
        result["image_url"] = _data_uri(data)
    except Exception as exc:
        result["failed"] = 1
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Cover image generation failed: %s", exc)
    return result


async def generate_concept_images(
    items: list[dict[str, Any]], output_dir: str | Path
) -> dict[str, Any]:
    """Populate each item with a cached AI-generated data URI."""
    config = ConceptImageConfig.from_env()
    result = ConceptImageBatchResult(enabled=config.enabled, model=config.model)
    if not config.enabled or not items:
        return result.to_dict()

    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        result.failed = len(items)
        result.errors["configuration"] = (
            f"missing image API key environment variable {config.api_key_env}"
        )
        return result.to_dict()

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(config.concurrency)
    timeout = httpx.Timeout(config.timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout, trust_env=config.trust_env) as client:

        async def generate_one(item: dict[str, Any]) -> None:
            item_id = str(item.get("id") or item.get("title") or "unknown")
            path = _cache_path(target_dir, item, config)
            try:
                if path.exists() and path.stat().st_size > 0:
                    data = path.read_bytes()
                    result.cached += 1
                else:
                    async with semaphore:
                        data = await _request_image(
                            client, config, api_key, build_concept_prompt(item)
                        )
                    path.write_bytes(data)
                    result.generated += 1
                item["image_url"] = _data_uri(data)
                item["concept_image_path"] = str(path)
                result.images.append(str(path))
            except Exception as exc:
                result.failed += 1
                result.errors[item_id] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Concept image generation failed for %s: %s", item_id, exc
                )

        await asyncio.gather(*(generate_one(item) for item in items))

    return result.to_dict()


async def generate_mechanism_images(
    items: list[dict[str, Any]], output_dir: str | Path
) -> dict[str, Any]:
    """Populate report items with a separate explanatory mechanism image."""
    config = ConceptImageConfig.from_env()
    result = ConceptImageBatchResult(enabled=config.enabled, model=config.model)
    eligible = [
        item
        for item in items
        if str(item.get("what_happened") or "").strip()
        and str(item.get("fresh_relationship") or "").strip()
    ]
    if not config.enabled or not eligible:
        return result.to_dict()

    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        result.failed = len(eligible)
        result.errors["configuration"] = (
            f"missing image API key environment variable {config.api_key_env}"
        )
        return result.to_dict()

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(config.concurrency)
    timeout = httpx.Timeout(config.timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout, trust_env=config.trust_env) as client:

        async def generate_one(item: dict[str, Any]) -> None:
            item_id = str(item.get("id") or item.get("title") or "unknown")
            path = _mechanism_cache_path(target_dir, item, config)
            try:
                if path.exists() and path.stat().st_size > 0:
                    data = path.read_bytes()
                    result.cached += 1
                else:
                    async with semaphore:
                        data = await _request_image(
                            client,
                            config,
                            api_key,
                            build_mechanism_prompt(item),
                            size=config.mechanism_size,
                            quality=config.quality,
                        )
                    path.write_bytes(data)
                    result.generated += 1
                item["mechanism_image_url"] = _data_uri(data)
                item["mechanism_image_path"] = str(path)
                result.images.append(str(path))
            except Exception as exc:
                result.failed += 1
                result.errors[item_id] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Mechanism image generation failed for %s: %s", item_id, exc
                )

        await asyncio.gather(*(generate_one(item) for item in eligible))

    return result.to_dict()


async def generate_composition_images(
    items: list[dict[str, Any]], output_dir: str | Path
) -> dict[str, Any]:
    """Let the final visual agent create one text-free atmosphere plate per card."""
    config = ConceptImageConfig.from_env()
    result = CompositionImageBatchResult(enabled=config.enabled, model=config.model)
    eligible = [
        item
        for item in items
        if str(item.get("what_happened") or "").strip()
        and str(item.get("fresh_relationship") or "").strip()
    ]
    if not config.enabled or not config.composition_enabled or not eligible:
        result.enabled = config.enabled and config.composition_enabled
        return result.to_dict()

    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        result.failed = len(eligible)
        result.errors["configuration"] = (
            f"missing image API key environment variable {config.api_key_env}"
        )
        return result.to_dict()

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(config.concurrency)
    timeout = httpx.Timeout(config.timeout_seconds)
    provider_unavailable = asyncio.Event()
    provider_error = ""

    async with httpx.AsyncClient(timeout=timeout, trust_env=config.trust_env) as client:

        async def generate_one(item: dict[str, Any]) -> None:
            nonlocal provider_error
            item_id = str(item.get("id") or item.get("title") or "unknown")
            references = _reference_image_bytes(item)
            prompt = build_composition_prompt(item, reference_count=len(references))
            path = _composition_cache_path(target_dir, item, config, references)
            mode = "cached"
            try:
                if path.exists() and path.stat().st_size > 0:
                    data = path.read_bytes()
                    result.cached += 1
                else:
                    async with semaphore:
                        if provider_unavailable.is_set():
                            raise RuntimeError(
                                "visual composition skipped after provider failure: "
                                + provider_error
                            )
                        if references:
                            try:
                                data, transport = await _request_image_edit(
                                    client,
                                    config,
                                    api_key,
                                    prompt,
                                    references,
                                    size=config.composition_size,
                                    quality=config.composition_quality,
                                )
                                result.edited += 1
                                mode = "edit"
                                result.transports[item_id] = transport
                            except Exception as edit_exc:
                                logger.warning(
                                    "Visual composition edit failed for %s; "
                                    "falling back to generation: %s",
                                    item_id,
                                    edit_exc,
                                )
                                try:
                                    data = await _request_image(
                                        client,
                                        config,
                                        api_key,
                                        prompt,
                                        size=config.composition_size,
                                        quality=config.composition_quality,
                                    )
                                except Exception as generation_exc:
                                    raise RuntimeError(
                                        "visual composition edit failed "
                                        f"({edit_exc}); generation fallback failed "
                                        f"({type(generation_exc).__name__}: "
                                        f"{generation_exc})"
                                    ) from generation_exc
                                result.fallbacks += 1
                                mode = "generation_fallback"
                        else:
                            data = await _request_image(
                                client,
                                config,
                                api_key,
                                prompt,
                                size=config.composition_size,
                                quality=config.composition_quality,
                            )
                            mode = "generation"
                    path.write_bytes(data)
                    result.generated += 1
                item["composition_image_url"] = _data_uri(data)
                item["composition_image_path"] = str(path)
                item["composition_mode"] = mode
                result.images.append(str(path))
                result.modes[item_id] = mode
            except Exception as exc:
                if not provider_unavailable.is_set():
                    provider_error = f"{type(exc).__name__}: {exc}"
                    provider_unavailable.set()
                result.failed += 1
                result.errors[item_id] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Visual composition generation failed for %s: %s", item_id, exc
                )

        await asyncio.gather(*(generate_one(item) for item in eligible))

    return result.to_dict()


class CardVisualAgent:
    """Generate the two visual assets used by each editorial card."""

    async def generate(
        self,
        items: list[dict[str, Any]],
        output_root: str | Path,
    ) -> dict[str, Any]:
        root = Path(output_root)
        concept_images = await generate_concept_images(
            items, root / "concept-images"
        )
        mechanism_images = await generate_mechanism_images(
            items, root / "mechanism-images"
        )
        composition_images = CompositionImageBatchResult(
            enabled=False,
            model="disabled",
        ).to_dict()
        complete_items = sum(
            bool(item.get("image_url") and item.get("mechanism_image_url"))
            for item in items
        )
        return {
            "concept_images": concept_images,
            "mechanism_images": mechanism_images,
            "composition_images": composition_images,
            "complete_items": complete_items,
            "orchestrated_items": 0,
            "requested_items": len(items),
        }
