"""Generate complete Markdown reports and Xiaohongshu-style image decks."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .image_generation import (
    CardVisualAgent,
    generate_cover_image,
)


REPORT_THEME = {
    "paper": "#F1EADB",
    "paper_soft": "#E5DAC5",
    "ink": "#2D2923",
    "muted": "#6F6659",
    "line": "#B8AA92",
    "brand": "#C94F3D",
    "cover": "#D6B84A",
    "map_blue": "#55788A",
    "terracotta": "#A85F48",
    "moss": "#78806B",
    "ink_purple": "#75677A",
    "brass": "#A77A3B",
}
CONTENT_TOPIC_DEFINITIONS = (
    ("gameplay-mechanics", "玩法与机制", REPORT_THEME["brand"]),
    ("world-level", "世界与关卡", REPORT_THEME["map_blue"]),
    ("narrative-culture", "叙事与文化", REPORT_THEME["terracotta"]),
    ("visual-experience", "视觉与体验", REPORT_THEME["ink_purple"]),
    ("player-market", "玩家行为与市场", REPORT_THEME["moss"]),
    ("production-tech", "技术与制作方法", REPORT_THEME["brass"]),
)
PRODUCT_NAME = "游戏创意雷达"
PRODUCT_COLOR = REPORT_THEME["brand"]
COVER_ACCENT = REPORT_THEME["cover"]


def _plain_text(value: Any) -> str:
    if not value:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\[tool-[^\]]+\]", "", text)
    return re.sub(r"\s+", " ", text).replace("`", "").strip()


def _truncate(value: str, limit: int) -> str:
    value = _plain_text(value)
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip("，。；：,.!? ") + "…"


def _mechanism_steps(value: Any) -> list[str]:
    text = _plain_text(value)
    if not text:
        return []
    parts = re.split(r"\s*(?:→|->|=>|｜|\||\n)\s*", text)
    steps = [_truncate(part, 12) for part in parts if _plain_text(part)]
    return steps[:4] if len(steps) >= 2 else []


def _image_url(item: dict[str, Any]) -> str | None:
    soup = BeautifulSoup(str(item.get("content") or ""), "html.parser")
    image = soup.find("img", src=True)
    if not image:
        return None
    value = str(image.get("src") or "").strip()
    return value if value.startswith(("https://", "http://")) else None


def _report_date(meta: dict[str, Any]) -> str:
    raw = meta.get("created_at") or meta.get("updated_at")
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _normalize_item(
    item: dict[str, Any],
    content_sections: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    processing = item.get("processing") or {}
    analysis = processing.get("analysis") or {}
    artifact = (processing.get("artifacts") or {}).get("zh") or {}
    blocks = artifact.get("blocks") or []
    by_id = {str(block.get("id")): block for block in blocks}
    what_happened = by_id.get("what_happened")
    mechanism_chain = by_id.get("mechanism_chain")
    fresh_relationship = by_id.get("fresh_relationship")
    systems_question = by_id.get("systems_question")
    game_question = by_id.get("game_question")
    metadata = item.get("metadata") or {}
    category = str(metadata.get("category") or "other")
    classification = processing.get("classification") or {}
    content_topic_id = str(classification.get("profile") or "")
    if content_topic_id in content_sections:
        section_name, color = content_sections[content_topic_id]
        section_id = content_topic_id
    else:
        section_id, section_name, color = "other", "未分类", REPORT_THEME["muted"]
    score = analysis.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "id": str(item.get("id") or ""),
        "title": _plain_text(
            artifact.get("title") or item.get("title") or "未命名资讯"
        ),
        "original_title": _plain_text(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "score": score,
        "category": category,
        "section_id": section_id,
        "section": section_name,
        "color": color,
        "what_happened": _plain_text(
            (what_happened or {}).get("content")
            or analysis.get("summary")
            or item.get("content")
        ),
        "fresh_relationship": _plain_text(
            (fresh_relationship or {}).get("content") or ""
        ),
        "event_heading": _plain_text((what_happened or {}).get("title") or ""),
        "insight_heading": _plain_text((fresh_relationship or {}).get("title") or ""),
        "systems_question": _plain_text((systems_question or {}).get("content") or ""),
        "systems_heading": _plain_text((systems_question or {}).get("title") or ""),
        "mechanism_steps": _mechanism_steps(
            (mechanism_chain or {}).get("content") or ""
        ),
        "game_question": _plain_text((game_question or {}).get("content") or ""),
        "reason": _plain_text(analysis.get("reason") or ""),
        "tags": [
            _plain_text(tag)
            for tag in (analysis.get("tags") or metadata.get("tags") or [])
            if _plain_text(tag)
        ][:8],
        "source": _plain_text(
            metadata.get("feed_name")
            or item.get("author")
            or item.get("source_type")
            or "未知来源"
        ),
        "published_at": str(item.get("published_at") or ""),
        "source_image_url": _image_url(item),
        "concept_image_url": None,
        "mechanism_image_url": None,
        "related_sources": [
            {
                "title": _plain_text(source.get("title") or "补充来源"),
                "url": str(source.get("url") or ""),
            }
            for source in (artifact.get("sources") or [])
            if source.get("url")
        ],
    }


def _is_publishable_item(item: dict[str, Any]) -> bool:
    processing = item.get("processing") or {}
    artifact = (processing.get("artifacts") or {}).get("zh") or {}
    blocks = artifact.get("blocks") or []
    content_by_id = {
        str(block.get("id")): _plain_text(block.get("content") or "")
        for block in blocks
        if isinstance(block, dict)
    }
    return bool(
        content_by_id.get("what_happened") and content_by_id.get("fresh_relationship")
    )


def build_report_model(
    *, run_id: str, items: list[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any]:
    configured_topics = meta.get("content_topics") or []
    if configured_topics:
        content_topic_rows = sorted(
            (
                (
                    str(topic.get("id") or ""),
                    str(topic.get("name") or topic.get("id") or "未命名板块"),
                    str(topic.get("color") or REPORT_THEME["muted"]),
                    int(topic.get("order") or 100),
                )
                for topic in configured_topics
                if topic.get("id")
            ),
            key=lambda row: (row[3], row[0]),
        )
    else:
        content_topic_rows = [
            (*row, index) for index, row in enumerate(CONTENT_TOPIC_DEFINITIONS)
        ]
    content_sections = {
        topic_id: (name, color) for topic_id, name, color, _ in content_topic_rows
    }
    normalized = sorted(
        (
            _normalize_item(item, content_sections)
            for item in items
            if _is_publishable_item(item)
        ),
        key=lambda item: (-item["score"], item["title"]),
    )
    sections = []
    for section_id, name, color, _ in content_topic_rows:
        section_items = [
            item for item in normalized if item["section_id"] == section_id
        ]
        if section_items:
            sections.append(
                {
                    "id": section_id,
                    "name": name,
                    "color": color,
                    "items": section_items,
                }
            )
    other_items = [item for item in normalized if item["section_id"] == "other"]
    if other_items:
        sections.append(
            {
                "id": "other",
                "name": "未分类",
                "color": REPORT_THEME["muted"],
                "items": other_items,
            }
        )

    fetched = int(meta.get("raw_count") or len(normalized))
    selected = len(normalized)
    rejected = int(meta.get("enrichment_rejected_count") or 0)
    enrichment_failed = int(meta.get("enrichment_failed_count") or 0)
    filtered = int(meta.get("filtered_count") or selected)
    lead = normalized[0] if normalized else None
    if lead:
        overview = (
            f"今天扫过 {fetched} 条材料，留下 {selected} 个值得聊聊的点。"
            f"先看《{lead['title']}》。"
        )
    elif rejected and not enrichment_failed and rejected >= filtered:
        overview = (
            f"今天扫过 {fetched} 条材料，候选材料经过深挖后全部退稿，"
            "没有留下足够扎实的核心发现。"
        )
    elif rejected:
        overview = f"今天扫过 {fetched} 条材料，深挖后没有留下可发布的核心发现。"
    else:
        overview = f"今天扫过 {fetched} 条材料，没有留下足够具体的游戏点子。"
    return {
        "run_id": run_id,
        "date": _report_date(meta),
        "name": PRODUCT_NAME,
        "color": PRODUCT_COLOR,
        "fetched": fetched,
        "selected": selected,
        "lead": lead,
        "sections": sections,
        "items": normalized,
        "overview": overview,
        "source_count": len({item["source"] for item in normalized}),
        "stats": {
            "fetched": fetched,
            "scored": int(meta.get("scored_count") or 0),
            "filtered": filtered,
            "enriched": int(meta.get("enriched_count") or selected),
            "rejected": rejected,
        },
    }


def build_markdown(model: dict[str, Any]) -> str:
    date = model["date"]
    lines = [
        f"# {model['name']} - {date}",
        "",
        (
            f"> Horizon Run: `{model['run_id']}` · 抓取 {model['fetched']} 条"
            f" · 发现 {model['selected']} 条创意线索"
        ),
        "",
        "## 今日概览",
        "",
        model["overview"],
        "",
    ]
    for section in model["sections"]:
        lines.extend([f"## {section['name']}", ""])
        for item in section["items"]:
            item_lines = [
                f"### [{item['title']}]({item['url']}) · 灵感值 {item['score']:.1f}/10",
                "",
                f"**发生了什么：** {item['what_happened']}",
                "",
            ]
            if item["mechanism_steps"]:
                item_lines.extend(
                    [f"**机制链：** {' → '.join(item['mechanism_steps'])}", ""]
                )
            if item["fresh_relationship"]:
                item_lines.extend(
                    [f"**真正好玩的地方：** {item['fresh_relationship']}", ""]
                )
            if item["systems_question"]:
                item_lines.extend(
                    [f"**再往下问一层：** {item['systems_question']}", ""]
                )
            if item["game_question"]:
                item_lines.extend(
                    [f"**它可能启发哪一类游戏问题：** {item['game_question']}", ""]
                )
            lines.extend(item_lines)
            if item["related_sources"]:
                links = " · ".join(
                    f"[{source['title']}]({source['url']})"
                    for source in item["related_sources"]
                )
                lines.extend([f"**补充来源：** {links}", ""])
            lines.extend(
                [
                    f"来源：{item['source']} · {item['published_at']}",
                    "",
                    "---",
                    "",
                ]
            )

    stats = model["stats"]
    lines.extend(
        [
            "## 生成方法",
            "",
            (
                f"本期依次完成抓取（{stats['fetched']} 条）、AI 评分（{stats['scored']} 条）、"
                f"灵感筛选（{stats['filtered']} 条）、关系提炼（{stats['enriched']} 条）、"
                f"深挖退稿（{stats.get('rejected', 0)} 条）。"
            ),
            "",
            "Horizon 在后台先把事件讲清楚，再判断它是否留下了值得带走的设计启发；只有真正增加理解时，日报才补充关系或问题。n8n 负责定时编排与发布。",
            "",
            "原始事实、新鲜关系与设计问题分开呈现；问题用于启发，不代表原作者观点。",
            "",
        ]
    )
    return "\n".join(lines)


def _base_css(accent: str) -> str:
    return f"""
    :root {{
      --paper: {REPORT_THEME["paper"]};
      --paper-soft: {REPORT_THEME["paper_soft"]};
      --ink: {REPORT_THEME["ink"]};
      --muted: {REPORT_THEME["muted"]};
      --line: {REPORT_THEME["line"]};
      --brand: {REPORT_THEME["brand"]};
      --cover: {REPORT_THEME["cover"]};
      --map-blue: {REPORT_THEME["map_blue"]};
      --terracotta: {REPORT_THEME["terracotta"]};
      --moss: {REPORT_THEME["moss"]};
      --ink-purple: {REPORT_THEME["ink_purple"]};
      --brass: {REPORT_THEME["brass"]};
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: 1080px; height: 1440px; overflow: hidden; }}
    body {{
      font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", "Source Han Sans SC", Arial, sans-serif;
      color: var(--ink); background: var(--paper); letter-spacing: 0;
      -webkit-font-smoothing: antialiased;
    }}
    .page {{ position: relative; width: 1080px; height: 1440px; overflow: hidden; background: var(--paper); }}
    .page::before {{ content: ""; position: absolute; z-index: 0; left: 0; right: 0; bottom: 0; pointer-events: none; }}
    .item-page::before {{ display: none; }}
    .cover-page::before {{ display: none; }}
    .directory-page::before {{ top: 500px; background: var(--paper-soft); border-top: 1px solid var(--line); }}
    .content {{ position: relative; z-index: 1; height: 100%; }}
    .top {{ position: absolute; z-index: 5; left: 0; right: 0; top: 0; min-height: 92px; padding: 0 58px; display: flex; align-items: center; justify-content: space-between; background: color-mix(in srgb, var(--paper) 92%, transparent); border-bottom: 3px solid {accent}; color: var(--ink); font: 700 17px "Noto Sans Mono CJK SC", monospace; backdrop-filter: blur(14px); }}
    .brand {{ display: flex; align-items: baseline; gap: 10px; }}
    .brand strong {{ color: {accent}; font-size: 20px; }}
    .brand b {{ color: var(--muted); }}
    .meta {{ display: flex; align-items: center; gap: 18px; font-variant-numeric: tabular-nums; }}
    .score {{ padding: 8px 11px; background: {accent}; color: var(--ink); font-size: 18px; }}
    h1, h2, h3, p {{ margin: 0; }}
    .page-backdrop {{ position: absolute; z-index: 0; inset: 0; overflow: hidden; background: var(--paper); }}
    .page-backdrop img {{ width: 100%; height: 100%; display: block; object-fit: cover; filter: blur(30px) saturate(.58) contrast(.94); transform: scale(1.08); opacity: .18; }}
    .page-backdrop::after {{ content: ""; position: absolute; inset: 0; background: color-mix(in srgb, var(--paper) 78%, transparent); }}
    .hero {{ position: absolute; inset: 92px 0 auto; height: 558px; margin: 0; overflow: hidden; background: #d8cdb8; }}
    .hero img {{ width: 100%; height: 100%; object-fit: cover; display: block; filter: saturate(.78) contrast(1.08); }}
    .hero::after {{ content: ""; position: absolute; inset: 0; background: linear-gradient(to bottom, color-mix(in srgb, var(--paper) 4%, transparent) 26%, color-mix(in srgb, var(--paper) 96%, transparent) 100%); }}
    .hero.no-image {{ height: 430px; border-bottom: 1px solid var(--line); }}
    .hero.no-image::after {{ display: none; }}
    .hero-title {{ position: absolute; z-index: 2; left: 58px; right: 58px; top: 404px; height: 216px; overflow: hidden; }}
    .hero-title.no-image {{ top: 186px; }}
    .hero.with-mechanism {{ height: 418px; }}
    .hero-title.with-mechanism {{ top: 286px; }}
    .body.with-mechanism {{ top: 510px; }}
    .eyebrow {{ display: inline-flex; padding: 9px 14px 10px; background: {accent}; color: var(--ink); font: 800 19px "Noto Sans Mono CJK SC", monospace; }}
    .title {{ margin-top: 16px; max-width: 930px; max-height: 174px; font: 700 62px/1.2 "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif; color: var(--ink); text-shadow: 0 2px 18px color-mix(in srgb, var(--paper) 72%, transparent); overflow: hidden; overflow-wrap: anywhere; }}
    .body {{ position: absolute; left: 58px; right: 58px; top: 670px; bottom: 44px; display: flex; flex-direction: column; overflow: hidden; padding-top: 10px; border-top: 1px solid rgba(74, 65, 53, .18); box-shadow: inset 0 28px 46px rgba(67, 52, 34, .08); }}
    .body.no-image {{ top: 438px; }}
    .copy {{ --copy-scale: 1; flex: 1 1 auto; min-height: 0; overflow: hidden; }}
    .fact {{ margin-top: 14px; padding: calc(22px * var(--copy-scale)) 24px calc(24px * var(--copy-scale)); border-left: 5px solid {accent}; border-bottom: 1px solid rgba(74, 65, 53, .16); background: rgba(232, 223, 204, .86); box-shadow: 0 12px 28px rgba(67, 52, 34, .1); }}
    .label {{ display: block; margin-bottom: calc(11px * var(--copy-scale)); color: var(--muted); font: 700 15px/1.2 "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif; letter-spacing: .04em; }}
    .fact p {{ margin: 0; color: var(--ink); font-size: calc(23px * var(--copy-scale)); line-height: 1.58; }}
    .relation {{ margin-top: 12px; padding: calc(22px * var(--copy-scale)) 24px calc(26px * var(--copy-scale)); border-left: 5px solid {accent}; border-bottom: 1px solid rgba(74, 65, 53, .16); position: relative; background: rgba(232, 223, 204, .86); box-shadow: 0 12px 28px rgba(67, 52, 34, .1); }}
    .relation .label {{ position: static; }}
    .mechanism-flow {{ display: flex; align-items: stretch; gap: 9px; margin: 0 0 calc(17px * var(--copy-scale)); }}
    .mechanism-node {{ flex: 1 1 0; min-width: 0; min-height: calc(62px * var(--copy-scale)); padding: calc(10px * var(--copy-scale)) 10px; display: flex; align-items: center; justify-content: center; border-top: 3px solid {accent}; background: var(--paper-soft); color: var(--ink); text-align: center; font-size: calc(17px * var(--copy-scale)); font-weight: 700; line-height: 1.32; overflow-wrap: anywhere; }}
    .mechanism-node:last-of-type {{ background: {accent}; color: var(--ink); }}
    .mechanism-arrow {{ flex: 0 0 18px; display: flex; align-items: center; justify-content: center; color: {accent}; font-size: calc(24px * var(--copy-scale)); font-weight: 800; }}
    .mechanism-visual {{ height: calc(178px * var(--copy-scale)); margin: 0 0 calc(15px * var(--copy-scale)); overflow: hidden; background: #e8e0cf; border-top: 3px solid {accent}; box-shadow: 0 10px 24px rgba(67, 52, 34, .12); }}
    .mechanism-visual img {{ width: 100%; height: 100%; display: block; object-fit: cover; object-position: 50% 50%; filter: saturate(.88) contrast(1.04); }}
    .mechanism-caption {{ margin: calc(-5px * var(--copy-scale)) 0 calc(14px * var(--copy-scale)); color: var(--muted); font-size: calc(15px * var(--copy-scale)); font-weight: 600; line-height: 1.35; }}
    .relation blockquote {{ margin: 0; padding: 0; border: 0; font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif; font-size: calc(29px * var(--copy-scale)); font-weight: 600; line-height: 1.44; color: var(--ink); }}
    .systems-question {{ margin-top: calc(15px * var(--copy-scale)); padding: calc(17px * var(--copy-scale)) 22px calc(19px * var(--copy-scale)); border-top: 4px solid {accent}; background: var(--paper-soft); box-shadow: 0 10px 24px rgba(67, 52, 34, .12), inset 0 1px rgba(250, 246, 236, .7); }}
    .systems-question .label {{ margin-bottom: calc(9px * var(--copy-scale)); color: {accent}; font-size: calc(14px * var(--copy-scale)); }}
    .systems-question p {{ color: var(--ink); font: 700 calc(20px * var(--copy-scale))/1.5 "Noto Serif CJK SC", "Microsoft YaHei UI", serif; }}
    .copy.has-mechanism .fact {{ padding-top: calc(15px * var(--copy-scale)); padding-bottom: calc(17px * var(--copy-scale)); }}
    .copy.has-mechanism .relation {{ padding-top: calc(17px * var(--copy-scale)); padding-bottom: calc(19px * var(--copy-scale)); }}
    .item-page {{ background: var(--paper); color: var(--ink); }}
    .item-page .top {{ min-height: 72px; padding: 0 36px; background: color-mix(in srgb, var(--paper) 97%, transparent); border-bottom: 1px solid {accent}; backdrop-filter: none; }}
    .item-page .brand strong {{ font-size: 18px; }}
    .item-page .brand span {{ color: var(--muted); font-size: 17px; }}
    .item-page .meta {{ gap: 16px; color: var(--muted); }}
    .item-page .score {{ padding: 8px 12px; font-size: 17px; }}
    .editorial-hero {{ position: absolute; left: 36px; right: 36px; top: 88px; height: 350px; overflow: hidden; background: #e5dcc8; border: 1px solid rgba(74, 65, 53, .22); }}
    .editorial-hero-copy {{ position: absolute; z-index: 3; left: 0; top: 0; bottom: 0; width: 55%; min-width: 0; padding: 46px 34px 28px 8px; }}
    .editorial-tags {{ display: flex; gap: 14px; align-items: center; min-height: 36px; overflow: hidden; }}
    .editorial-tag {{ display: inline-flex; max-width: 240px; padding: 8px 12px; border: 1px solid {accent}; border-radius: 3px; color: {accent}; font-size: 16px; font-weight: 800; line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .editorial-title {{ margin-top: 22px; width: 540px; max-width: 100%; height: 178px; overflow: hidden; color: var(--ink); font: 900 60px/1.12 "Noto Serif CJK SC", "Microsoft YaHei UI", serif; text-wrap: balance; text-shadow: none; }}
    .editorial-deck {{ position: absolute; left: 8px; right: 36px; bottom: 20px; min-height: 58px; padding-top: 15px; border-top: 1px solid color-mix(in srgb, var(--brand) 62%, transparent); color: var(--muted); font-size: 17px; line-height: 1.48; white-space: normal; overflow: visible; }}
    .editorial-deck::before {{ content: ""; position: absolute; left: 0; top: -2px; width: 42px; height: 3px; background: {accent}; }}
    .editorial-hero-media {{ position: absolute; z-index: 1; inset: 0; margin: 0; overflow: hidden; background: #ddd3bc; }}
    .editorial-hero-media .media-fit {{ position: absolute; z-index: 1; right: 0; top: 0; width: 64%; height: 100%; display: block; object-fit: contain; object-position: right center; filter: saturate(.84) contrast(1.06) brightness(.82); }}
    .editorial-hero-media::after {{ content: ""; position: absolute; z-index: 2; inset: 0; background: linear-gradient(90deg, var(--paper) 0%, var(--paper) 40%, color-mix(in srgb, var(--paper) 97%, transparent) 47%, color-mix(in srgb, var(--paper) 75%, transparent) 56%, color-mix(in srgb, var(--paper) 30%, transparent) 67%, transparent 80%); }}
    .editorial-hero-media.no-image {{ background: radial-gradient(circle at 70% 48%, #d4cbb6 0, #e4dbc7 32%, var(--paper) 76%); }}
    .event-strip {{ --copy-scale: 1; position: absolute; left: 36px; right: 36px; top: 452px; height: 210px; display: grid; grid-template-columns: 118px 310px minmax(0, 1fr); align-items: center; border: 1px solid color-mix(in srgb, var(--ink) 22%, transparent); background: var(--paper-soft); overflow: hidden; }}
    .insight-symbol {{ position: relative; width: 70px; height: 70px; margin: auto; border: 1px solid rgba(232, 74, 60, .66); border-radius: 50%; }}
    .insight-symbol::before, .insight-symbol::after {{ content: ""; position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); border-radius: 50%; }}
    .insight-symbol::before {{ width: 34px; height: 34px; border: 4px solid {accent}; box-shadow: 0 0 0 7px rgba(232, 74, 60, .12); }}
    .insight-symbol::after {{ width: 8px; height: 8px; background: {accent}; box-shadow: -25px 0 0 -2px {accent}, 25px 0 0 -2px {accent}, 0 -25px 0 -2px {accent}, 0 25px 0 -2px {accent}; }}
    .event-index {{ align-self: stretch; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 15px; border-right: 1px solid color-mix(in srgb, var(--ink) 18%, transparent); }}
    .event-index .insight-symbol {{ margin: 0; }}
    .event-index b {{ color: {accent}; font-size: 16px; line-height: 1; }}
    .agent-lead {{ align-self: stretch; display: flex; flex-direction: column; justify-content: center; padding: 0 28px 0 24px; border-right: 1px solid color-mix(in srgb, var(--ink) 22%, transparent); }}
    .agent-lead h2 {{ color: var(--ink); font: 800 calc(25px * var(--copy-scale))/1.3 "Noto Serif CJK SC", "Microsoft YaHei UI", serif; }}
    .agent-body {{ margin: 0; color: color-mix(in srgb, var(--ink) 78%, var(--muted)); font: 500 calc(17px * var(--copy-scale))/1.58 "Microsoft YaHei UI", "PingFang SC", sans-serif; }}
    .event-body {{ --copy-scale: 1; height: 178px; padding: 0 30px; overflow: hidden; }}
    .mechanism-board {{ position: absolute; left: 36px; right: 36px; top: 662px; height: 300px; display: grid; grid-template-columns: 108px minmax(0, 1fr); border: 1px solid color-mix(in srgb, var(--ink) 22%, transparent); background: var(--paper-soft); overflow: hidden; }}
    .mechanism-board:has(.mechanism-strip) {{ background: #ddd3bd; }}
    .section-index {{ display: flex; flex-direction: column; align-items: flex-start; padding: 34px 20px 0 26px; border-right: 1px solid color-mix(in srgb, var(--ink) 18%, transparent); }}
    .section-index strong {{ color: {accent}; font: 800 48px/1 "Noto Sans Mono CJK SC", monospace; }}
    .section-index i {{ width: 34px; height: 2px; margin: 14px 0; background: {accent}; }}
    .section-index b {{ margin-bottom: 10px; color: {accent}; font-size: 14px; line-height: 1.25; white-space: nowrap; }}
    .section-index span {{ color: var(--muted); font: 500 11px/1.55 "Noto Sans Mono CJK SC", monospace; text-transform: uppercase; }}
    .mechanism-main {{ position: relative; min-width: 0; padding: 0; overflow: hidden; }}
    .board-title {{ color: {accent}; font-size: 21px; font-weight: 900; }}
    .mechanism-strip {{ position: absolute; inset: 12px 14px; margin: 0; overflow: hidden; border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent); border-radius: 4px; background: var(--paper-soft); }}
    .mechanism-strip .media-fit {{ position: relative; z-index: 1; width: 100%; height: 100%; display: block; object-fit: cover; object-position: 50% 100%; filter: saturate(.92) contrast(1.06) brightness(.92); }}
    .mechanism-strip::after {{ content: ""; position: absolute; z-index: 2; inset: 0; background: linear-gradient(180deg, rgba(72, 57, 35, .1), transparent 28%, transparent 82%, rgba(72, 57, 35, .12)); pointer-events: none; }}
    .mechanism-step-labels {{ display: none; }}
    .mechanism-fallback {{ margin-top: 28px; min-height: 190px; display: flex; align-items: center; justify-content: center; padding: 30px; border: 1px solid color-mix(in srgb, var(--ink) 22%, transparent); color: var(--ink); background: var(--paper-soft); font: 800 25px/1.4 "Noto Serif CJK SC", serif; text-align: center; }}
    .bottom-board {{ position: absolute; left: 36px; right: 36px; top: 976px; height: 360px; display: grid; grid-template-columns: 48% 52%; border: 1px solid color-mix(in srgb, var(--ink) 22%, transparent); background: var(--paper-soft); overflow: hidden; }}
    .design-panel, .question-panel {{ display: grid; grid-template-columns: 108px minmax(0, 1fr); min-width: 0; min-height: 0; overflow: hidden; }}
    .question-panel {{ border-left: 1px solid color-mix(in srgb, var(--ink) 20%, transparent); }}
    .design-content, .question-content {{ min-width: 0; padding: 31px 24px 22px; }}
    .design-content {{ --copy-scale: 1; height: 100%; min-height: 0; padding: calc(31px * var(--copy-scale)) 24px calc(20px * var(--copy-scale)); overflow: hidden; }}
    .design-content .board-title {{ font-size: calc(21px * var(--copy-scale)); }}
    .question-content {{ --copy-scale: 1; height: 100%; min-height: 0; padding: calc(31px * var(--copy-scale)) 24px calc(22px * var(--copy-scale)); overflow: hidden; }}
    .question-content .board-title {{ font-size: calc(21px * var(--copy-scale)); }}
    .panel-heading {{ margin-bottom: calc(14px * var(--copy-scale)); color: var(--ink); font: 800 calc(22px * var(--copy-scale))/1.32 "Noto Serif CJK SC", serif; }}
    .panel-body {{ color: var(--muted); font: 500 calc(17px * var(--copy-scale))/1.62 "Microsoft YaHei UI", "PingFang SC", sans-serif; }}
    .editorial-footer {{ position: absolute; left: 40px; right: 40px; bottom: 22px; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 18px; color: var(--muted); font: 500 14px "Noto Sans Mono CJK SC", monospace; }}
    .editorial-footer-line {{ height: 1px; background: linear-gradient(90deg, color-mix(in srgb, var(--brand) 65%, transparent), color-mix(in srgb, var(--ink) 24%, transparent)); }}
    .footer {{ position: absolute; left: 0; right: 0; bottom: 0; display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; color: var(--muted); font: 500 14px "Noto Sans Mono CJK SC", monospace; }}
    .body > .footer {{ position: static; flex: 0 0 24px; padding-top: 8px; }}
    .cover-body, .overview-body, .method-body {{ position: absolute; left: 58px; right: 58px; top: 190px; bottom: 44px; }}
    .cover-page {{ background: var(--paper); color: var(--ink); }}
    .cover-page .top {{ min-height: 94px; padding: 0 54px; background: transparent; border-bottom: 0; color: var(--ink); }}
    .cover-page .brand {{ gap: 18px; }}
    .cover-page .brand strong {{ color: var(--brand); font-size: 25px; }}
    .cover-page .brand b {{ display: none; }}
    .cover-page .brand span {{ color: var(--muted); font: 800 17px "Noto Sans CJK SC", sans-serif; }}
    .cover-page .meta {{ color: var(--ink); font-size: 16px; }}
    .cover-art {{ position: absolute; z-index: 0; left: 0; right: 0; top: 338px; height: 866px; margin: 0; overflow: hidden; background: var(--paper-soft); }}
    .cover-art img {{ width: 100%; height: 100%; object-fit: cover; object-position: 50% 52%; display: block; filter: saturate(.84) contrast(1.04); }}
    .cover-art::after {{ content: ""; position: absolute; inset: 0; background: linear-gradient(to bottom, var(--paper) 0%, color-mix(in srgb, var(--paper) 94%, transparent) 6%, color-mix(in srgb, var(--paper) 54%, transparent) 17%, color-mix(in srgb, var(--paper) 8%, transparent) 31%, color-mix(in srgb, var(--ink) 2%, transparent) 76%, color-mix(in srgb, var(--ink) 26%, transparent) 100%); }}
    .cover-art.no-image {{ background: linear-gradient(160deg, var(--paper) 0 34%, var(--paper-soft) 68%, #c9bda6 100%); }}
    .cover-art.no-image::after {{ display: none; }}
    .cover-poster-body {{ position: absolute; z-index: 2; inset: 0; }}
    .cover-headline {{ position: absolute; left: 54px; top: 144px; width: 590px; color: var(--ink); font: 900 86px/.96 "Noto Serif CJK SC", serif; }}
    .cover-headline span {{ display: block; }}
    .cover-headline span + span {{ margin-top: 7px; }}
    .cover-issue {{ position: absolute; left: 653px; top: 126px; color: var(--ink); font: 800 14px "Noto Sans Mono CJK SC", monospace; writing-mode: vertical-rl; text-orientation: mixed; letter-spacing: .04em; }}
    .cover-count-panel {{ position: absolute; right: 54px; top: 100px; width: 316px; height: 316px; padding: 38px 28px 24px; background: {accent}; color: var(--ink); border-top: 9px solid var(--ink); }}
    .cover-count-panel strong {{ display: block; font: 900 166px/.72 "Noto Sans Mono CJK SC", monospace; font-variant-numeric: tabular-nums; }}
    .cover-count-panel span {{ display: block; margin-top: 33px; font: 900 27px/1.14 "Noto Serif CJK SC", serif; }}
    .cover-summary {{ position: absolute; left: 0; right: 0; top: 1196px; height: 244px; padding: 36px 54px 22px; color: var(--ink); background: var(--paper-soft); border-top: 8px solid var(--cover); }}
    .cover-summary p {{ max-width: 900px; font: 700 25px/1.48 "Noto Serif CJK SC", serif; }}
    .cover-taxonomy {{ display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 28px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font: 800 15px "Noto Sans Mono CJK SC", monospace; }}
    .cover-taxonomy span:nth-child(2) {{ text-align: center; }}
    .cover-taxonomy span:last-child {{ text-align: right; }}
    .directory-body {{ position: absolute; left: 58px; right: 58px; top: 150px; bottom: 44px; }}
    .directory-title {{ margin-top: 22px; color: var(--ink); font: 900 66px/1.08 "Noto Serif CJK SC", serif; }}
    .directory-lede {{ margin-top: 16px; color: var(--muted); font: 600 21px/1.45 "Noto Serif CJK SC", serif; }}
    .directory-body .metrics {{ margin-top: 32px; }}
    .directory-body .metric {{ min-height: 112px; padding-top: 18px; }}
    .directory-body .metric strong {{ font-size: 43px; }}
    .directory-body .metric span {{ margin-top: 10px; font-size: 17px; }}
    .cover-summary-body {{ position: absolute; left: 58px; right: 58px; top: 150px; bottom: 44px; }}
    .cover-summary-title {{ margin-top: 18px; font: 900 58px/1.12 "Noto Serif CJK SC", serif; color: var(--ink); }}
    .cover-summary-lede {{ margin-top: 16px; color: var(--muted); font: 600 21px/1.45 "Noto Serif CJK SC", serif; }}
    .cover-summary-body .metrics {{ margin-top: 30px; }}
    .cover-summary-body .metric {{ min-height: 112px; padding-top: 18px; }}
    .cover-summary-body .metric strong {{ font-size: 43px; }}
    .cover-summary-body .metric span {{ margin-top: 10px; font-size: 17px; }}
    .directory-head {{ display: flex; align-items: baseline; justify-content: space-between; margin-top: 28px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }}
    .directory-head strong {{ font: 800 20px "Noto Serif CJK SC", serif; color: var(--ink); }}
    .directory-head span {{ color: var(--muted); font: 500 14px "Noto Sans Mono CJK SC", monospace; }}
    .directory-grid {{ display: grid; gap: 0 30px; margin-top: 4px; }}
    .directory-column {{ min-width: 0; }}
    .directory-row {{ display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 10px; align-items: center; min-height: 58px; border-bottom: 1px solid var(--line); color: var(--ink); font-size: 18px; }}
    .directory-row strong {{ color: {accent}; font: 700 15px "Noto Sans Mono CJK SC", monospace; }}
    .directory-row span {{ overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
    .directory-grid[data-columns="3"] {{ gap: 0 20px; }}
    .directory-grid[data-columns="3"] .directory-row {{ grid-template-columns: 30px minmax(0, 1fr); gap: 7px; min-height: 54px; font-size: 16px; }}
    .directory-grid[data-columns="3"] .directory-row strong {{ font-size: 13px; }}
    .cover-title {{ margin-top: 22px; max-width: 900px; font: 900 78px/1.15 "Noto Serif CJK SC", serif; color: var(--ink); }}
    .cover-lede {{ margin-top: 38px; max-width: 860px; color: var(--muted); font: 600 30px/1.58 "Noto Serif CJK SC", serif; }}
    .cover-count {{ margin-top: 90px; display: flex; align-items: flex-end; gap: 24px; }}
    .cover-count strong {{ color: {accent}; font: 900 178px/.8 "Noto Sans Mono CJK SC", monospace; }}
    .cover-count span {{ color: var(--muted); font-size: 24px; line-height: 1.45; padding-bottom: 8px; }}
    .overview-title, .method-title {{ margin-top: 22px; font: 900 62px/1.15 "Noto Serif CJK SC", serif; color: var(--ink); }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 54px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .metric {{ min-height: 142px; padding: 24px 20px 20px 0; }}
    .metric + .metric {{ border-left: 1px solid var(--line); padding-left: 28px; }}
    .metric strong {{ display: block; color: {accent}; font: 900 52px/1 "Noto Sans Mono CJK SC", monospace; }}
    .metric span {{ display: block; margin-top: 14px; color: var(--muted); font-size: 19px; }}
    .overview-list {{ margin-top: 42px; }}
    .overview-row {{ display: flex; align-items: center; gap: 22px; padding: 18px 0; border-top: 1px solid var(--line); color: var(--ink); font-size: 23px; }}
    .overview-row strong {{ width: 42px; color: {accent}; font: 700 19px "Noto Sans Mono CJK SC", monospace; }}
    .method-steps {{ margin-top: 58px; border-top: 1px solid var(--line); }}
    .method-step {{ display: grid; grid-template-columns: 150px 1fr 90px; gap: 22px; padding: 28px 0; border-bottom: 1px solid var(--line); align-items: center; color: var(--ink); font-size: 22px; }}
    .method-step strong {{ color: var(--ink); }}
    .method-step b {{ color: {accent}; font: 700 30px "Noto Sans Mono CJK SC", monospace; text-align: right; }}
    .method-lede {{ margin-top: 42px; color: var(--muted); font: 600 24px/1.58 "Noto Serif CJK SC", serif; }}
    """


def _html_page(body: str, *, accent: str, title: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_base_css(accent)}</style></head>"
        f"<body>{body}{_fit_script()}</body></html>"
    )


def _fit_script() -> str:
    return """
    <script>
    (() => {
      const fitCopy = () => {
        document.querySelectorAll('[data-fit-copy]').forEach((copy) => {
          let scale = 1;
          while (copy.scrollHeight > copy.clientHeight && scale > 0.68) {
            scale -= 0.02;
            copy.style.setProperty('--copy-scale', scale.toFixed(2));
          }
        });
        document.querySelectorAll('[data-fit-title]').forEach((title) => {
          let size = parseFloat(getComputedStyle(title).fontSize);
          while (title.scrollHeight > title.clientHeight && size > 42) {
            size -= 2;
            title.style.fontSize = `${size}px`;
          }
        });
      };
      fitCopy();
      requestAnimationFrame(fitCopy);
      if (document.fonts?.ready) {
        document.fonts.ready.then(() => {
          fitCopy();
          requestAnimationFrame(fitCopy);
        });
      }
    })();
    </script>
    """


def _shell(
    content: str,
    *,
    accent: str,
    index: int,
    total: int,
    score: float | None = None,
    page_kind: str | None = None,
) -> str:
    score_html = (
        f'<strong class="score">{score:.1f} 分</strong>' if score is not None else ""
    )
    page_class = (
        f"{page_kind}-page"
        if page_kind
        else ("item-page" if score is not None else "cover-page")
    )
    return f"""
    <main class="page {page_class}" style="--accent: {accent}"><div class="content">
      <div class="top"><div class="brand"><strong>HORIZON</strong><b>/</b><span>游戏创意雷达</span></div><div class="meta"><span>{index:02d} / {total:02d}</span>{score_html}</div></div>
      {content}
    </div></main>
    """


def _legacy_build_card_html(
    model: dict[str, Any], max_cards: int = 12
) -> list[dict[str, str]]:
    available_item_pages = max(0, max_cards - 3)
    featured = model["items"][:available_item_pages]
    total = 3 + len(featured)
    date_label = model["date"].replace("-", ".")
    lead = model["lead"]
    cards: list[dict[str, str]] = []

    cover_content = f"""
      <div class="eyebrow">GAME IDEAS RADAR · {date_label}</div>
      <h1 class="title" style="font-size:78px;max-width:900px;margin-top:48px">{html.escape(model["name"])}</h1>
      <p class="lede" style="margin-top:44px">从真实故事和奇怪现象里，找到值得借用的新鲜关系，以及可以继续追问的游戏问题。</p>
      <div style="margin-top:72px;display:flex;align-items:flex-end;gap:28px"><strong style="font-size:188px;line-height:.8;font-variant-numeric:tabular-nums">{model["selected"]:02d}</strong><span style="font-size:25px;line-height:1.5;padding-bottom:8px">条创意线索<br>值得继续追问</span></div>
      <div class="footer"><span>RSSHub × Horizon × n8n</span><span>{date_label}</span></div>
    """
    cards.append(
        {
            "slug": "cover",
            "html": _html_page(
                _shell(cover_content, accent=model["color"], index=1, total=total),
                accent=model["color"],
                title=model["name"],
            ),
        }
    )

    model_list = "".join(
        f'<div style="display:flex;align-items:center;gap:22px;border-top:1px solid {REPORT_THEME["line"]};padding:18px 0;font-size:25px"><strong style="color:{REPORT_THEME["map_blue"]};width:42px">{index:02d}</strong><span>{html.escape(_truncate(item["title"], 34))}</span></div>'
        for index, item in enumerate(model["items"][:5], start=1)
    )
    overview_content = f"""
      <div class="eyebrow">今日总览</div>
      <h1 class="title medium">今天发现了<br>哪些创意线索</h1>
      <div class="metric-row" style="margin-top:54px">
        <div class="metric"><strong>{model["fetched"]}</strong><span>候选材料</span></div>
        <div class="metric"><strong>{model["selected"]}</strong><span>创意线索</span></div>
        <div class="metric"><strong>{model["source_count"]}</strong><span>灵感来源</span></div>
      </div>
      <div style="margin-top:44px">{model_list}</div>
      <div class="footer"><span>今日首选</span><strong style="max-width:720px;text-align:right;font-size:23px">{html.escape(_truncate((lead or {}).get("title", "暂无创意线索"), 42))}</strong></div>
    """
    cards.append(
        {
            "slug": "overview",
            "html": _html_page(
                _shell(overview_content, accent=REPORT_THEME["map_blue"], index=2, total=total),
                accent=REPORT_THEME["map_blue"],
                title="今日总览",
            ),
        }
    )

    for item_index, item in enumerate(featured, start=1):
        card_index = 2 + item_index
        title_class = "small" if len(item["title"]) > 35 else "medium"
        image_block = ""
        if item.get("concept_image_url"):
            image_block = f"""
              <div style="margin-top:28px;height:180px;border-top:2px solid {REPORT_THEME["ink"]};border-bottom:2px solid {REPORT_THEME["ink"]};overflow:hidden;background:{REPORT_THEME["paper_soft"]}">
                <img src="{html.escape(item["concept_image_url"], quote=True)}" style="width:100%;height:100%;object-fit:cover;display:block" />
              </div>
            """
        else:
            image_block = f"""
              <div style="margin-top:28px;height:122px;background:{item["color"]};color:{REPORT_THEME["ink"]};padding:24px 30px;display:flex;align-items:flex-end;justify-content:space-between">
                <span style="font-size:23px;font-weight:700">INSPIRATION</span><strong style="font-size:92px;line-height:.82">{item["score"]:.1f}</strong>
              </div>
            """
        item_content = f"""
          <div class="eyebrow">创意线索 {item_index:02d} · 关系与问题</div>
          <h1 class="title {title_class}" style="font-size:48px">{html.escape(item["title"])}</h1>
          {image_block}
          <div style="margin-top:24px;border-left:8px solid {item["color"]};padding-left:22px;font-size:21px;line-height:1.48;color:{REPORT_THEME["ink"]}"><strong style="font-size:24px">发生了什么</strong><br>{html.escape(_truncate(item["what_happened"], 170))}</div>
          <div style="margin-top:24px;background:{REPORT_THEME["paper_soft"]};border-top:6px solid {item["color"]};padding:22px 26px;font-size:21px;line-height:1.48;color:{REPORT_THEME["ink"]}"><strong style="font-size:24px">真正新鲜的关系是什么</strong><br><span style="display:block;margin-top:10px">{html.escape(_truncate(item["fresh_relationship"], 190))}</span></div>
          <div style="margin-top:24px;border-top:2px solid {REPORT_THEME["ink"]};padding-top:20px;font-size:21px;line-height:1.48;color:{REPORT_THEME["ink"]}"><strong style="font-size:24px">它可能启发哪一类游戏问题</strong><br><span style="display:block;margin-top:10px">{html.escape(_truncate(item["game_question"], 190))}</span></div>
          <div class="footer"><span>{html.escape(item["source"])} · 灵感值 {item["score"]:.1f}</span><span>{html.escape(item["published_at"][:10])}</span></div>
        """
        cards.append(
            {
                "slug": f"item-{item_index:02d}",
                "html": _html_page(
                    _shell(
                        item_content,
                        accent=item["color"],
                        index=card_index,
                        total=total,
                    ),
                    accent=item["color"],
                    title=item["title"],
                ),
            }
        )

    stats = model["stats"]
    method_index = total
    method_content = f"""
      <div class="eyebrow">生成方法</div>
      <h1 class="title medium">一条材料如何<br>变成创意线索</h1>
      <div style="margin-top:58px;border-top:2px solid {REPORT_THEME["ink"]}">
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid {REPORT_THEME["line"]};align-items:center"><strong style="font-size:28px">01 抓取</strong><span style="font-size:24px">RSS / RSSHub 汇集候选信号</span><b style="font-size:32px;text-align:right">{stats["fetched"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid {REPORT_THEME["line"]};align-items:center"><strong style="font-size:28px">02 评分</strong><span style="font-size:24px">寻找具体关系、反常和结果</span><b style="font-size:32px;text-align:right">{stats["scored"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid {REPORT_THEME["line"]};align-items:center"><strong style="font-size:28px">03 筛选</strong><span style="font-size:24px">留下能形成玩家动作的材料</span><b style="font-size:32px;text-align:right">{stats["filtered"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:2px solid {REPORT_THEME["ink"]};align-items:center"><strong style="font-size:28px">04 提炼</strong><span style="font-size:24px">新鲜关系与开放的游戏问题</span><b style="font-size:32px;text-align:right">{stats["enriched"]}</b></div>
      </div>
      <p class="lede" style="font-size:25px;margin-top:42px">每条创意线索只回答三件事：发生了什么、其中哪段关系真正新鲜、它可以打开哪类游戏问题。图片组展示 {len(featured)} 条，完整 Markdown 保留全部 {model["selected"]} 条。</p>
      <div class="footer"><span>RSSHub → Horizon → n8n</span><span>{date_label}</span></div>
    """
    cards.append(
        {
            "slug": "method",
            "html": _html_page(
                _shell(
                    method_content, accent=REPORT_THEME["ink"], index=method_index, total=total
                ),
                accent=REPORT_THEME["ink"],
                title="数据与方法",
            ),
        }
    )
    return cards


def build_card_html(model: dict[str, Any], max_cards: int = 12) -> list[dict[str, str]]:
    """Build the unified cinematic report deck used by the daily output."""
    available_item_pages = max(0, max_cards - 2)
    featured = model["items"][:available_item_pages]
    total = 2 + len(featured)
    date_label = model["date"].replace("-", ".")
    cards: list[dict[str, str]] = []

    item_count = len(model["items"])
    directory_columns = 1 if item_count <= 10 else 2 if item_count <= 20 else 3
    rows_per_column = max(1, (item_count + directory_columns - 1) // directory_columns)
    directory_columns_html = []
    for column_index in range(directory_columns):
        start = column_index * rows_per_column
        column_items = model["items"][start : start + rows_per_column]
        rows = "".join(
            f'<div class="directory-row"><strong>{item_index:02d}</strong><span>{html.escape(_truncate(item["title"], 26 if directory_columns == 1 else 18 if directory_columns == 2 else 12))}</span></div>'
            for item_index, item in enumerate(column_items, start=start + 1)
        )
        directory_columns_html.append(f'<div class="directory-column">{rows}</div>')
    directory_html = "".join(directory_columns_html)

    lead = model.get("lead") or {}
    cover_image = model.get("cover_image_url") or lead.get("concept_image_url")
    if cover_image:
        cover_art = f'<figure class="cover-art"><img src="{html.escape(cover_image, quote=True)}" alt=""></figure>'
    else:
        cover_art = '<div class="cover-art no-image" aria-hidden="true"></div>'
    if item_count:
        cover_headline = "<span>从真实世界</span><span>长出游戏</span>"
        cover_count_label = "个值得偷走的<br>游戏创意"
        cover_summary_copy = (
            f"从今日 {model['fetched']} 条现实材料里，寻找机制、世界与叙事<br>"
            "如何在同一套关系中互相驱动。"
        )
    else:
        cover_headline = "<span>今天不硬凑</span><span>一个发现</span>"
        cover_count_label = "候选经过深挖<br>全部退稿"
        cover_summary_copy = html.escape(model["overview"])
    cover_content = f"""
      {cover_art}
      <section class="cover-poster-body">
        <div class="cover-issue">RELATIONSHIP ECOLOGY · {html.escape(date_label)}</div>
        <h1 class="cover-headline">{cover_headline}</h1>
        <div class="cover-count-panel"><strong>{item_count:02d}</strong><span>{cover_count_label}</span></div>
        <div class="cover-summary">
          <p>{cover_summary_copy}</p>
          <div class="cover-taxonomy"><span>MECHANIC</span><span>WORLD</span><span>STORY</span></div>
        </div>
      </section>
    """
    cards.append(
        {
            "slug": "cover",
            "html": _html_page(
                _shell(
                    cover_content,
                    accent=COVER_ACCENT,
                    index=1,
                    total=total,
                    page_kind="cover",
                ),
                accent=COVER_ACCENT,
                title=model["name"],
            ),
        }
    )

    directory_content = f"""
      <section class="directory-body">
        <div class="eyebrow">CONTENTS · {html.escape(date_label)}</div>
        <h1 class="directory-title">今天发现了什么</h1>
        <p class="directory-lede">先把有意思的几条挑出来，再慢慢看细节。</p>
        <div class="metrics">
          <div class="metric"><strong>{model["fetched"]}</strong><span>候选材料</span></div>
          <div class="metric"><strong>{model["selected"]}</strong><span>创意线索</span></div>
          <div class="metric"><strong>{model["source_count"]}</strong><span>灵感来源</span></div>
        </div>
        <div class="directory-head"><strong>今日创意总览</strong><span>共 {item_count} 条 · 按评分排序</span></div>
        <div class="directory-grid" data-columns="{directory_columns}" style="grid-template-columns:repeat({directory_columns}, minmax(0, 1fr))">{directory_html}</div>
        <div class="footer"><span>RSSHub × Horizon × n8n</span><span>完整目录</span></div>
      </section>
    """
    cards.append(
        {
            "slug": "directory",
            "html": _html_page(
                _shell(
                    directory_content,
                    accent=COVER_ACCENT,
                    index=2,
                    total=total,
                    page_kind="directory",
                ),
                accent=COVER_ACCENT,
                title="今日创意目录",
            ),
        }
    )

    for item_index, item in enumerate(featured, start=1):
        card_index = 2 + item_index
        title = html.escape(item["title"])
        event_heading_text = item.get("event_heading") or _truncate(
            item["what_happened"], 28
        )
        event_heading = html.escape(event_heading_text)
        insight_heading = html.escape(
            item.get("insight_heading")
            or _truncate(item["fresh_relationship"], 34)
        )
        event_copy = html.escape(item.get("what_happened") or "")
        insight_copy = html.escape(item.get("fresh_relationship") or "")
        systems_question_copy = html.escape(item.get("systems_question") or "")
        systems_heading = html.escape(item.get("systems_heading") or "继续追问")
        if item.get("concept_image_url"):
            hero_url = html.escape(item["concept_image_url"], quote=True)
            hero_media = (
                '<figure class="editorial-hero-media">'
                f'<img class="media-fit" src="{hero_url}" alt="">'
                "</figure>"
            )
        else:
            hero_media = (
                '<div class="editorial-hero-media no-image" aria-hidden="true"></div>'
            )
        if item.get("mechanism_image_url"):
            mechanism_url = html.escape(item["mechanism_image_url"], quote=True)
            mechanism_visual = (
                '<figure class="mechanism-strip">'
                f'<img class="media-fit" src="{mechanism_url}" alt="">'
                "</figure>"
            )
        else:
            mechanism_visual = f'<div class="mechanism-fallback">{event_heading} → {insight_heading}</div>'
        systems_question_content = (
            f'<h2 class="panel-heading">{systems_heading}</h2>'
            f'<p class="panel-body" data-agent-copy="systems">{systems_question_copy}</p>'
            if systems_question_copy
            else ""
        )
        item_content = f"""
          <section class="editorial-hero">
            <div class="editorial-hero-copy">
              <div class="editorial-tags">
                <span class="editorial-tag">{html.escape(item["section"])}</span>
              </div>
              <h1 class="editorial-title" data-fit-title>{title}</h1>
            </div>
            {hero_media}
          </section>
          <section class="event-strip" data-field-label="事件">
            <div class="event-index">
              <div class="insight-symbol" aria-hidden="true"></div>
              <b>事件</b>
            </div>
            <div class="agent-lead">
              <h2>{event_heading}</h2>
            </div>
            <p class="agent-body event-body" data-agent-copy="event" data-fit-copy>{event_copy}</p>
          </section>
          <section class="mechanism-board">
            <div class="section-index"><strong>01</strong><i></i><b>事件过程</b></div>
            <div class="mechanism-main">
              {mechanism_visual}
            </div>
          </section>
          <section class="bottom-board">
            <div class="design-panel" data-field-label="设计启示">
              <div class="section-index"><strong>02</strong><i></i><b>设计启示</b></div>
              <div class="design-content" data-fit-copy>
                <h2 class="panel-heading">{insight_heading}</h2>
                <p class="panel-body" data-agent-copy="insight">{insight_copy}</p>
              </div>
            </div>
            <div class="question-panel">
              <div class="section-index"><strong>03</strong><i></i><b>系统追问</b></div>
              <div class="question-content" data-fit-copy>
                {systems_question_content}
              </div>
            </div>
          </section>
          <div class="editorial-footer">
            <span>{html.escape(item["source"])} · {item["score"]:.1f} 分</span>
            <i class="editorial-footer-line"></i>
            <span>{html.escape(item["published_at"][:10])}</span>
          </div>
        """
        cards.append(
            {
                "slug": f"item-{item_index:02d}",
                "html": _html_page(
                    _shell(
                        item_content,
                        accent=PRODUCT_COLOR,
                        index=card_index,
                        total=total,
                        score=item["score"],
                    ),
                    accent=PRODUCT_COLOR,
                    title=item["title"],
                ),
            }
        )

    return cards


async def generate_xiaohongshu_report(
    *,
    run_id: str,
    items: list[dict[str, Any]],
    meta: dict[str, Any],
    max_cards: int = 12,
    output_root: str | Path | None = None,
    browserless_url: str | None = None,
) -> dict[str, Any]:
    model = build_report_model(run_id=run_id, items=items, meta=meta)
    root = Path(output_root or os.getenv("HORIZON_REPORT_OUTPUT_DIR", "/app/output"))
    report_dir = root / f"game-inspiration-radar-{model['date']}-{run_id}"
    html_dir = report_dir / "html"
    cards_dir = report_dir / "cards"
    html_dir.mkdir(parents=True, exist_ok=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    for artifact_dir, pattern in ((html_dir, "*.html"), (cards_dir, "*.png")):
        for artifact_path in artifact_dir.glob(pattern):
            artifact_path.unlink()

    markdown_path = report_dir / "report.md"
    markdown_path.write_text(build_markdown(model), encoding="utf-8")
    featured_count = max(0, max_cards - 2)
    card_visuals, cover_image = await asyncio.gather(
        CardVisualAgent().generate(model["items"][:featured_count], report_dir),
        generate_cover_image(
            model["items"],
            report_dir / "cover-art",
            report_date=model["date"],
            run_id=run_id,
            fetched_count=model["fetched"],
        ),
    )
    concept_images = card_visuals["concept_images"]
    mechanism_images = card_visuals["mechanism_images"]
    composition_images = card_visuals["composition_images"]
    model["cover_image_url"] = cover_image.get("image_url")
    card_specs = build_card_html(model, max_cards=max_cards)
    endpoint = browserless_url or os.getenv(
        "BROWSERLESS_SCREENSHOT_URL", "http://rsshub-browserless:3000/screenshot"
    )
    rendered: list[str] = []
    async with httpx.AsyncClient(timeout=90.0) as client:
        for index, card in enumerate(card_specs, start=1):
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
        "date": model["date"],
        "name": model["name"],
        "fetched": model["fetched"],
        "selected": model["selected"],
        "markdown": str(markdown_path),
        "cards": rendered,
        "card_count": len(rendered),
        "image_size": "1080x1440",
        "concept_images": concept_images,
        "mechanism_images": mechanism_images,
        "composition_images": composition_images,
        "card_visuals": {
            "complete_items": card_visuals["complete_items"],
            "orchestrated_items": card_visuals["orchestrated_items"],
            "requested_items": card_visuals["requested_items"],
        },
        "cover_image": {
            key: value for key, value in cover_image.items() if key != "image_url"
        },
    }
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
