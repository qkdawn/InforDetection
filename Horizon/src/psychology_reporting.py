"""Render a digital-life psychology discussion as four Xiaohongshu cards."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .image_generation import ConceptImageConfig, _data_uri, _request_image


PRODUCT_NAME = "屏幕里的我们"
ACCENT = "#c95443"
INK = "#262321"
PAPER = "#f7f2ec"
MUTED = "#796f69"
logger = logging.getLogger(__name__)


def _date() -> str:
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def _headline_size(value: str, *, cover: bool = False) -> int:
    length = len(value)
    if cover:
        return 92 if length <= 14 else 78 if length <= 22 else 66
    return 72 if length <= 9 else 66 if length <= 13 else 58 if length <= 22 else 50


def _base_css() -> str:
    return f"""
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: 1080px; height: 1440px; overflow: hidden; }}
    body {{ font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", Arial, sans-serif; color: {INK}; background: {PAPER}; letter-spacing: 0; -webkit-font-smoothing: antialiased; }}
    .page {{ position: relative; width: 1080px; height: 1440px; overflow: hidden; background: {PAPER}; }}
    .rail {{ position: absolute; z-index: 5; left: 58px; right: 58px; top: 42px; height: 58px; display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid {INK}; font-size: 16px; font-weight: 800; }}
    .brand {{ color: {ACCENT}; font-size: 22px; }}
    .page-no {{ font-family: "Cascadia Mono", "Noto Sans Mono CJK SC", monospace; }}
    .stage {{ position: absolute; z-index: 2; left: 72px; right: 72px; top: 154px; bottom: 100px; }}
    .eyebrow {{ display: inline-flex; align-items: center; gap: 11px; color: {ACCENT}; font-size: 17px; font-weight: 900; }}
    .eyebrow::before {{ content: ""; width: 30px; height: 4px; background: {ACCENT}; }}
    h1, h2, p, blockquote {{ margin: 0; }}
    h1, h2 {{ max-width: 900px; margin-top: 32px; font-family: "Noto Sans CJK SC", "Microsoft YaHei UI", "PingFang SC", sans-serif; font-weight: 900; line-height: 1.16; overflow-wrap: anywhere; }}
    .body {{ max-width: 840px; margin-top: 44px; color: #433e3a; font-size: 31px; font-weight: 550; line-height: 1.72; }}
    .pull {{ max-width: 860px; margin-top: 48px; padding: 24px 0 26px 30px; border-left: 7px solid {ACCENT}; font: 850 38px/1.45 "Noto Serif CJK SC", "STSong", serif; }}
    .takeaway {{ max-width: 790px; margin-top: 62px; padding: 30px 34px 32px; color: white; background: {INK}; font-size: 37px; font-weight: 900; line-height: 1.5; }}
    .takeaway.long {{ max-width: 860px; font-size: 27px; font-weight: 650; line-height: 1.65; }}
    .ghost {{ position: absolute; right: 42px; bottom: 6px; color: rgba(38,35,33,.075); font: 900 270px/.9 "Cascadia Mono", monospace; }}
    .page-art {{ position: absolute; z-index: 1; left: 72px; right: 72px; top: 790px; height: 510px; margin: 0; overflow: hidden; background: #ded6ce; }}
    .page-art img {{ width: 100%; height: 100%; display: block; object-fit: cover; object-position: center; filter: saturate(.82) contrast(1.04); }}
    .page-art::after {{ content: ""; position: absolute; inset: 0; border: 1px solid rgba(38,35,33,.15); pointer-events: none; }}
    .footer {{ position: absolute; z-index: 4; left: 72px; right: 72px; bottom: 34px; display: flex; justify-content: space-between; color: {MUTED}; font-size: 14px; font-weight: 700; }}
    .cover {{ background: {INK}; color: white; }}
    .cover .rail {{ border-color: rgba(255,255,255,.45); }}
    .cover .stage {{ z-index: 3; top: 164px; right: 106px; }}
    .cover h1 {{ max-width: 850px; margin-top: 28px; color: white; font-family: "Noto Serif CJK SC", "STSong", "Microsoft YaHei UI", serif; }}
    .cover .subtitle {{ max-width: 700px; margin-top: 34px; color: #e8e1dc; font-size: 26px; font-weight: 600; line-height: 1.55; }}
    .cover .eyebrow {{ color: #ff806f; }}
    .cover .eyebrow::before {{ background: #ff806f; }}
    .cover-art {{ position: absolute; z-index: 0; inset: 0; overflow: hidden; background: #424743; }}
    .cover-art img {{ width: 100%; height: 100%; display: block; object-fit: cover; object-position: center; filter: saturate(.78) contrast(1.05); }}
    .cover-art::after {{ content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(38,35,33,.84) 0%, rgba(38,35,33,.52) 32%, rgba(38,35,33,.12) 61%, rgba(38,35,33,.72) 100%); }}
    .cover .footer {{ z-index: 4; color: rgba(255,255,255,.72); }}
    .scene .stage {{ top: 164px; }}
    .scene h2 {{ max-width: 820px; }}
    .scene .body {{ max-width: 820px; margin-top: 58px; padding: 30px 34px 32px; border-left: 7px solid {ACCENT}; background: #ece4dc; }}
    .scene .takeaway {{ margin-top: 54px; }}
    .scene .page-art {{ top: 790px; height: 510px; }}
    .turn {{ color: white; background: {INK}; }}
    .turn .rail {{ border-color: rgba(255,255,255,.45); }}
    .turn .eyebrow {{ color: #ff7163; }}
    .turn .eyebrow::before {{ background: #ff7163; }}
    .turn h2 {{ color: white; }}
    .turn .body {{ color: #d9ddda; }}
    .turn .pull {{ color: white; border-color: #ff7163; }}
    .turn .stage {{ top: 164px; }}
    .turn .body {{ max-width: 800px; margin-top: 58px; padding-top: 28px; border-top: 2px solid rgba(255,255,255,.5); }}
    .turn .takeaway {{ margin-top: 62px; color: white; background: {ACCENT}; }}
    .turn .ghost {{ color: rgba(255,255,255,.075); }}
    .turn .footer {{ color: rgba(255,255,255,.68); }}
    .turn .page-art {{ top: 790px; height: 510px; background: #36312e; }}
    .turn .page-art img {{ filter: saturate(.72) contrast(1.08) brightness(.82); }}
    .turn .page-art::after {{ border-color: rgba(255,255,255,.16); background: linear-gradient(180deg, rgba(38,35,33,.14), rgba(38,35,33,.42)); }}
    .aftertaste .stage {{ top: 164px; }}
    .aftertaste h2 {{ max-width: 860px; }}
    .aftertaste .body {{ max-width: 850px; margin-top: 68px; padding-top: 30px; border-top: 3px solid {INK}; font-size: 29px; }}
    .aftertaste .takeaway {{ margin-top: 56px; }}
    .aftertaste .page-art {{ top: 710px; height: 590px; }}
    """


def _page_shell(content: str, *, role: str, index: int, total: int, title: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1080, initial-scale=1"><title>{html.escape(title)}</title><style>{_base_css()}</style></head><body><main class="page {role}"><header class="rail"><span class="brand">{PRODUCT_NAME}</span><span class="page-no">{index:02d} / {total:02d}</span></header>{content}<footer class="footer"><span>数字生活心理现象</span><span>从一个问题，看见一种机制</span></footer></main></body></html>"""


def _text(value: Any) -> str:
    return html.escape(str(value or ""))


def build_psychology_cards(
    payload: dict[str, Any],
    cover_url: str | None = None,
    page_images: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    script = payload["script"]
    pages = script["pages"]
    total = len(pages)
    insight = payload.get("insight", {})
    deck_pull = next(
        (str(item.get("pull_quote", "")).strip() for item in pages if item.get("pull_quote")),
        "",
    )
    cards: list[dict[str, str]] = []
    resolved_images = dict(page_images or {})
    if cover_url and "cover" not in resolved_images:
        resolved_images["cover"] = cover_url
    for index, page in enumerate(pages, 1):
        role = page["role"]
        eyebrow = _text(page["eyebrow"])
        headline = _text(page["headline"])
        body = _text(page.get("body"))
        pull = _text(page.get("pull_quote"))
        image_url = resolved_images.get(role, "")
        art = (
            f'<figure class="page-art"><img src="{html.escape(image_url, quote=True)}" alt=""></figure>'
            if image_url
            else ""
        )
        if role == "cover":
            cover_art = (
                f'<figure class="cover-art"><img src="{html.escape(image_url, quote=True)}" alt=""></figure>'
                if image_url
                else '<figure class="cover-art"></figure>'
            )
            content = (
                f'{cover_art}<section class="stage"><div class="eyebrow">{eyebrow}</div>'
                f'<h1 style="font-size:{_headline_size(page["headline"], cover=True)}px">{headline}</h1>'
                f'<p class="subtitle">{body or _text(script["subtitle"])}</p></section>'
            )
        else:
            body_html = f'<p class="body">{body}</p>' if body else ""
            takeaway = ""
            takeaway_long = False
            if role == "scene":
                takeaway = pull or str(script.get("subtitle", "")).strip()
            elif role == "turn":
                takeaway = pull or str(insight.get("concept_definition", "")).strip() or deck_pull
            elif role == "aftertaste":
                takeaway = pull
                takeaway_long = True
            takeaway_html = (
                f'<aside class="takeaway{" long" if takeaway_long else ""}">{_text(takeaway)}</aside>'
                if takeaway
                else ""
            )
            content = (
                f'<section class="stage"><div class="eyebrow">{eyebrow}</div>'
                f'<h2 style="font-size:{_headline_size(page["headline"])}px">{headline}</h2>'
                f'{body_html}{takeaway_html}</section>{art}<span class="ghost">{index}</span>'
            )
        cards.append(
            {
                "slug": role,
                "html": _page_shell(
                    content, role=role, index=index, total=total, title=page["headline"]
                ),
            }
        )
    return cards


def build_psychology_markdown(payload: dict[str, Any]) -> str:
    script = payload["script"]
    insight = payload["insight"]
    review = payload.get("review", {})
    lines = [
        f"# {script['title']}",
        "",
        f"> {script['subtitle']}",
        "",
        f"原选题：{payload['topic']}",
        "",
        "## 核心洞察",
        "",
        insight["core_thesis"],
        "",
        "## 选角说明",
        "",
        f"**选中角度：** {insight.get('selected_label', '')}",
        "",
        f"**相比原题新增：** {insight.get('what_it_adds', '')}",
        "",
        f"**行为的隐秘收益：** {insight.get('hidden_payoff', '')}",
        "",
        f"**被转移的代价：** {insight.get('emotional_cost', '')}",
        "",
        "## 发布分镜",
        "",
    ]
    for index, page in enumerate(script["pages"], 1):
        lines.extend(
            [
                f"### {index}. {page['headline']}",
                "",
                page.get("body", ""),
                "",
            ]
        )
        if page.get("pull_quote"):
            lines.extend([f"> {page['pull_quote']}", ""])
    lines.extend(
        [
            "## 小红书文案",
            "",
            script["caption"],
            "",
            " ".join(f"#{tag}" for tag in script["tags"]),
            "",
            "## 主编检查",
            "",
            f"结论：{review.get('verdict', 'pass')}",
            "",
        ]
    )
    for note in review.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(["", "> 这是数字生活心理现象的解释性讨论，不用于判断人格或进行心理诊断。", ""])
    return "\n".join(lines)


def _series_visual_bible() -> str:
    return "\n".join(
        [
            "Series visual bible: sophisticated paper editorial illustration for a Chinese digital-life psychology column.",
            "Medium: hand-cut paper collage combined with matte gouache, dry-brush ink, deckled torn edges, subtle recycled-paper fibers, and restrained vintage print grain.",
            "Image language: turn one ordinary digital-life object or domestic gesture into a precise psychological metaphor. Objects must remain recognizable and physically grounded; emotion comes from spacing, interruption, repetition, or an unfinished action.",
            "Palette: warm ivory paper, charcoal black, muted clay red, dusty sage, and at most one small faded teal accent. Matte pigment only; no glossy rendering and no gradients.",
            "Continuity: every page belongs to the same illustrator, same paper stock, same pigment density, same edge treatment, and same restrained color system.",
            "Human presence: hands or partial silhouettes may appear only when the action requires them. No visible face, no sad person staring at a phone, and no melodramatic pose.",
            "Constraints: image only. No words, letters, numbers, logos, watermarks, captions, UI screenshots, speech bubbles, brains, hearts, floating icons, neon, bokeh, therapy-room imagery, or literal explanatory diagrams.",
        ]
    )


def _page_art_prompt(payload: dict[str, Any], page: dict[str, Any]) -> str:
    insight = payload["insight"]
    role = page["role"]
    role_direction = {
        "cover": (
            "Create the series cover metaphor: one strong still-life tableau that makes the "
            "question instantly felt. Portrait 2:3. Keep the upper 42 percent calm and low-detail "
            "for overlaid Chinese title typography; place the key objects in the middle and lower half."
        ),
        "scene": (
            "Show the recognizable everyday moment immediately before or after the behavior. "
            "Wide 3:2 composition, one clear action trace, with all important objects inside the "
            "middle 65 percent so a shallow card crop remains legible."
        ),
        "turn": (
            "Visualize the psychological mechanism through a single spatial metaphor: repetition, "
            "blocked continuation, branching choices, accumulating weight, or transferred pressure. "
            "Keep it concrete rather than diagrammatic. Wide 3:2, bold silhouette, few objects."
        ),
        "aftertaste": (
            "Create a quieter closing image that introduces distance, boundary, or a small opening "
            "without becoming optimistic decoration. Wide 3:2, generous breathing room, one unfinished "
            "gesture or object relationship that leaves a thoughtful afterimage."
        ),
    }[role]
    mechanism_steps = " -> ".join(insight.get("mechanism_steps") or [])
    return "\n".join(
        [
            "Use case: stylized-concept",
            f"Asset type: text-free artwork for page role '{role}' in a four-page Xiaohongshu psychology explainer",
            _series_visual_bible(),
            f"Discussion question: {payload['topic']}",
            f"Page idea: {page.get('headline', '')}",
            f"Page detail: {page.get('body', '')}",
            f"Observed moment: {insight.get('lived_moment', '')}",
            f"Hidden conflict: {insight.get('hidden_conflict', '')}",
            f"Psychology concept: {insight.get('psychology_concept', '')}",
            f"Mechanism chain: {mechanism_steps}",
            f"Recurring motif: {insight.get('visual_motif', '')}",
            f"Page direction: {role_direction}",
            "Avoid generic decorative collage. The chosen objects and their spatial relationship must specifically express this page's idea and remain readable at mobile thumbnail size.",
        ]
    )


async def _generate_page_art(
    payload: dict[str, Any], output_dir: Path
) -> dict[str, Any]:
    config = ConceptImageConfig.from_env()
    result: dict[str, Any] = {
        "enabled": config.enabled,
        "model": config.model,
        "generated": 0,
        "cached": 0,
        "failed": 0,
        "images": {},
        "image_urls": {},
        "errors": {},
        "prompts": {},
    }
    if not config.enabled:
        return result
    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        result.update(
            {
                "failed": len(payload["script"]["pages"]),
                "errors": {"configuration": f"missing {config.api_key_env}"},
            }
        )
        return result
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(config.concurrency)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout_seconds), trust_env=config.trust_env
    ) as client:

        async def generate_one(page: dict[str, Any]) -> None:
            role = page["role"]
            prompt = _page_art_prompt(payload, page)
            size = config.cover_size if role == "cover" else config.size
            quality = config.cover_quality
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "prompt": prompt,
                        "model": config.model,
                        "size": size,
                        "quality": quality,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:20]
            path = output_dir / f"{role}-{digest}.png"
            result["prompts"][role] = prompt
            try:
                if path.exists() and path.stat().st_size > 0:
                    data = path.read_bytes()
                    result["cached"] += 1
                else:
                    async with semaphore:
                        data = await _request_image(
                            client,
                            config,
                            api_key,
                            prompt,
                            size=size,
                            quality=quality,
                        )
                    path.write_bytes(data)
                    result["generated"] += 1
                result["images"][role] = str(path)
                result["image_urls"][role] = _data_uri(data)
            except Exception as exc:
                result["failed"] += 1
                result["errors"][role] = f"{type(exc).__name__}: {exc}"
                logger.warning("Psychology page art failed for %s: %s", role, exc)

        await asyncio.gather(
            *(generate_one(page) for page in payload["script"]["pages"])
        )
    return result


async def generate_psychology_report(
    *,
    run_id: str,
    payload: dict[str, Any],
    output_root: str | Path | None = None,
    browserless_url: str | None = None,
) -> dict[str, Any]:
    date = _date()
    root = Path(output_root or os.getenv("HORIZON_REPORT_OUTPUT_DIR", "/app/output"))
    report_dir = root / f"psychology-brief-{date}-{run_id}"
    html_dir = report_dir / "html"
    cards_dir = report_dir / "cards"
    html_dir.mkdir(parents=True, exist_ok=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "report.md"
    markdown_path.write_text(build_psychology_markdown(payload), encoding="utf-8")
    script_path = report_dir / "script.json"
    script_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    page_art = await _generate_page_art(payload, report_dir / "page-art")
    specs = build_psychology_cards(payload, page_images=page_art["image_urls"])
    endpoint = browserless_url or os.getenv(
        "BROWSERLESS_SCREENSHOT_URL", "http://rsshub-browserless:3000/screenshot"
    )
    rendered: list[str] = []
    async with httpx.AsyncClient(timeout=90.0) as client:
        for index, card in enumerate(specs, 1):
            html_path = html_dir / f"{index:02d}-{card['slug']}.html"
            png_path = cards_dir / f"{index:02d}-{card['slug']}.png"
            html_path.write_text(card["html"], encoding="utf-8")
            response = await client.post(
                endpoint,
                json={
                    "html": card["html"],
                    "viewport": {"width": 1080, "height": 1440, "deviceScaleFactor": 1},
                    "options": {"type": "png", "fullPage": False},
                },
            )
            response.raise_for_status()
            png_path.write_bytes(response.content)
            rendered.append(str(png_path))

    manifest = {
        "run_id": run_id,
        "date": date,
        "name": PRODUCT_NAME,
        "topic": payload["topic"],
        "title": payload["script"]["title"],
        "markdown": str(markdown_path),
        "script": str(script_path),
        "cards": rendered,
        "card_count": len(rendered),
        "image_size": "1080x1440",
        "page_art": {
            key: value for key, value in page_art.items() if key != "image_urls"
        },
    }
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
