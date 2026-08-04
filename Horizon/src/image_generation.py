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
    quality: str
    concurrency: int
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ConceptImageConfig":
        try:
            concurrency = int(os.getenv("HORIZON_IMAGE_CONCURRENCY", "2"))
        except ValueError:
            concurrency = 2
        try:
            timeout_seconds = float(
                os.getenv("HORIZON_IMAGE_TIMEOUT_SECONDS", "240")
            )
        except ValueError:
            timeout_seconds = 240.0
        return cls(
            enabled=os.getenv("HORIZON_IMAGE_GENERATION_ENABLED", "false").lower()
            in _TRUTHY,
            base_url=os.getenv(
                "HORIZON_IMAGE_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            api_key_env=os.getenv(
                "HORIZON_IMAGE_API_KEY_ENV", "OPENAI_API_KEY"
            ),
            model=os.getenv("HORIZON_IMAGE_MODEL", "gpt-image-2"),
            size=os.getenv("HORIZON_IMAGE_SIZE", "1536x1024"),
            quality=os.getenv("HORIZON_IMAGE_QUALITY", "low"),
            concurrency=max(1, min(concurrency, 4)),
            timeout_seconds=max(30.0, min(timeout_seconds, 600.0)),
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


async def _request_image(
    client: httpx.AsyncClient,
    config: ConceptImageConfig,
    api_key: str,
    prompt: str,
) -> bytes:
    response = await client.post(
        f"{config.base_url}/images/generations",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": config.model,
            "prompt": prompt,
            "size": config.size,
            "quality": config.quality,
            "n": 1,
        },
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") or []
    if not rows:
        raise ValueError("image API returned no data")
    row = rows[0]
    encoded = row.get("b64_json")
    if encoded:
        return base64.b64decode(encoded)
    image_url = row.get("url")
    if image_url:
        image_response = await client.get(image_url)
        image_response.raise_for_status()
        return image_response.content
    raise ValueError("image API returned neither b64_json nor url")


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

    async with httpx.AsyncClient(timeout=timeout) as client:

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
                logger.warning("Concept image generation failed for %s: %s", item_id, exc)

        await asyncio.gather(*(generate_one(item) for item in items))

    return result.to_dict()
