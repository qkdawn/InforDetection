"""Generate complete Markdown reports and Xiaohongshu-style image decks."""

from __future__ import annotations

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


CONTENT_TOPIC_DEFINITIONS = (
    ("gameplay-mechanics", "玩法与机制", "#e84a3c"),
    ("world-level", "世界与关卡", "#2b6cb0"),
    ("narrative-culture", "叙事与文化", "#32835c"),
    ("visual-experience", "视觉与体验", "#d43d74"),
    ("player-market", "玩家行为与市场", "#6d5bd0"),
    ("production-tech", "技术与制作方法", "#ba6b16"),
)
PRODUCT_NAME = "游戏创意雷达"
PRODUCT_COLOR = "#e84a3c"


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
    fresh_relationship = by_id.get("fresh_relationship")
    game_question = by_id.get("game_question")
    metadata = item.get("metadata") or {}
    category = str(metadata.get("category") or "other")
    classification = processing.get("classification") or {}
    content_topic_id = str(classification.get("profile") or "")
    if content_topic_id in content_sections:
        section_name, color = content_sections[content_topic_id]
        section_id = content_topic_id
    else:
        section_id, section_name, color = "other", "未分类", "#4b5563"
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
        "image_url": _image_url(item),
        "related_sources": [
            {
                "title": _plain_text(source.get("title") or "补充来源"),
                "url": str(source.get("url") or ""),
            }
            for source in (artifact.get("sources") or [])
            if source.get("url")
        ],
    }


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
                    str(topic.get("color") or "#4b5563"),
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
        (_normalize_item(item, content_sections) for item in items),
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
                "color": "#4b5563",
                "items": other_items,
            }
        )

    fetched = int(meta.get("raw_count") or len(normalized))
    selected = len(normalized)
    lead = normalized[0] if normalized else None
    overview = (
        f"本期从 {fetched} 条材料中发现 {selected} 条值得继续追问的创意线索。"
        f"最值得先看的是《{lead['title']}》。"
        if lead
        else f"本期抓取 {fetched} 条材料，暂未发现足够具体的创意线索。"
    )
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
            "filtered": int(meta.get("filtered_count") or selected),
            "enriched": int(meta.get("enriched_count") or selected),
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
            lines.extend(
                [
                    f"### [{item['title']}]({item['url']}) · 灵感值 {item['score']:.1f}/10",
                    "",
                    f"**发生了什么：** {item['what_happened']}",
                    "",
                    f"**真正新鲜的关系是什么：** {item['fresh_relationship']}",
                    "",
                    f"**它可能启发哪一类游戏问题：** {item['game_question']}",
                    "",
                ]
            )
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
                f"灵感筛选（{stats['filtered']} 条）、关系提炼（{stats['enriched']} 条）。"
            ),
            "",
            "Horizon 在后台识别来源中特有的异常关系；日报只展示发生了什么、真正新鲜的关系，以及它可能启发的游戏问题。n8n 负责定时编排与发布。",
            "",
            "原始事实、新鲜关系与设计问题分开呈现；问题用于启发，不代表原作者观点。",
            "",
        ]
    )
    return "\n".join(lines)


def _base_css(accent: str) -> str:
    return f"""
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: 1080px; height: 1440px; overflow: hidden; }}
    body {{
      font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
      color: #171717; background: #f6f5f1; letter-spacing: 0;
      -webkit-font-smoothing: antialiased;
    }}
    .page {{ position: relative; width: 1080px; height: 1440px; padding: 72px 76px 62px; overflow: hidden; }}
    .page::before {{ content: ""; position: absolute; inset: 0 0 auto 0; height: 14px; background: {accent}; }}
    .grid {{ position: absolute; inset: 0; pointer-events: none; opacity: .26;
      background-image: linear-gradient(#d8d7d2 1px, transparent 1px), linear-gradient(90deg, #d8d7d2 1px, transparent 1px);
      background-size: 72px 72px; mask-image: linear-gradient(to bottom, #000, transparent 62%); }}
    .content {{ position: relative; z-index: 1; height: 100%; display: flex; flex-direction: column; }}
    .top {{ display: flex; align-items: center; justify-content: space-between; font-size: 22px; font-weight: 700; color: #444; }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .mark {{ width: 18px; height: 18px; background: {accent}; }}
    .index {{ font-variant-numeric: tabular-nums; }}
    h1, h2, h3, p {{ margin: 0; }}
    .eyebrow {{ margin-top: 74px; color: {accent}; font-size: 26px; font-weight: 800; }}
    .title {{ margin-top: 22px; font-size: 72px; line-height: 1.14; font-weight: 900; overflow-wrap: anywhere; }}
    .title.medium {{ font-size: 62px; }}
    .title.small {{ font-size: 52px; line-height: 1.18; }}
    .lede {{ margin-top: 32px; max-width: 860px; font-size: 31px; line-height: 1.62; color: #353535; }}
    .rule {{ width: 100%; height: 2px; background: #202020; margin: 38px 0; }}
    .metric-row {{ display: grid; grid-template-columns: repeat(3, 1fr); border-top: 2px solid #202020; border-bottom: 2px solid #202020; }}
    .metric {{ min-height: 144px; padding: 24px 20px 20px 0; }}
    .metric + .metric {{ border-left: 1px solid #b8b8b4; padding-left: 28px; }}
    .metric strong {{ display: block; font-size: 52px; line-height: 1; font-variant-numeric: tabular-nums; }}
    .metric span {{ display: block; margin-top: 14px; font-size: 21px; color: #5b5b57; }}
    .footer {{ margin-top: auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; font-size: 20px; color: #595955; }}
    .footer .run {{ max-width: 680px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .pill-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
    .pill {{ border: 1px solid #a7a7a2; padding: 9px 14px; font-size: 19px; background: rgba(255,255,255,.68); }}
    """


def _html_page(body: str, *, accent: str, title: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_base_css(accent)}</style></head>"
        f"<body>{body}</body></html>"
    )


def _shell(content: str, *, accent: str, index: int, total: int) -> str:
    return f"""
    <main class="page"><div class="grid"></div><div class="content">
      <div class="top"><div class="brand"><span class="mark"></span>HORIZON / GAME IDEAS</div><div class="index">{index:02d} / {total:02d}</div></div>
      {content}
    </div></main>
    """


def build_card_html(model: dict[str, Any], max_cards: int = 12) -> list[dict[str, str]]:
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
        f'<div style="display:flex;align-items:center;gap:22px;border-top:1px solid #bdbdb8;padding:18px 0;font-size:25px"><strong style="color:#087f8c;width:42px">{index:02d}</strong><span>{html.escape(_truncate(item["title"], 34))}</span></div>'
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
                _shell(overview_content, accent="#087f8c", index=2, total=total),
                accent="#087f8c",
                title="今日总览",
            ),
        }
    )

    for item_index, item in enumerate(featured, start=1):
        card_index = 2 + item_index
        title_class = "small" if len(item["title"]) > 35 else "medium"
        image_block = ""
        if item["image_url"]:
            image_block = f"""
              <div style="margin-top:28px;height:180px;border-top:2px solid #1c1c1c;border-bottom:2px solid #1c1c1c;overflow:hidden;background:#ddd">
                <img src="{html.escape(item["image_url"], quote=True)}" style="width:100%;height:100%;object-fit:cover;display:block" />
              </div>
            """
        else:
            image_block = f"""
              <div style="margin-top:28px;height:122px;background:{item["color"]};color:white;padding:24px 30px;display:flex;align-items:flex-end;justify-content:space-between">
                <span style="font-size:23px;font-weight:700">INSPIRATION</span><strong style="font-size:92px;line-height:.82">{item["score"]:.1f}</strong>
              </div>
            """
        item_content = f"""
          <div class="eyebrow">创意线索 {item_index:02d} · 关系与问题</div>
          <h1 class="title {title_class}" style="font-size:48px">{html.escape(item["title"])}</h1>
          {image_block}
          <div style="margin-top:24px;border-left:8px solid {item["color"]};padding-left:22px;font-size:21px;line-height:1.48;color:#333"><strong style="font-size:24px">发生了什么</strong><br>{html.escape(_truncate(item["what_happened"], 170))}</div>
          <div style="margin-top:24px;background:#fff;border-top:6px solid {item["color"]};padding:22px 26px;font-size:21px;line-height:1.48;color:#292929"><strong style="font-size:24px">真正新鲜的关系是什么</strong><br><span style="display:block;margin-top:10px">{html.escape(_truncate(item["fresh_relationship"], 190))}</span></div>
          <div style="margin-top:24px;border-top:2px solid #202020;padding-top:20px;font-size:21px;line-height:1.48;color:#333"><strong style="font-size:24px">它可能启发哪一类游戏问题</strong><br><span style="display:block;margin-top:10px">{html.escape(_truncate(item["game_question"], 190))}</span></div>
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
      <div style="margin-top:58px;border-top:2px solid #202020">
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid #bdbdb8;align-items:center"><strong style="font-size:28px">01 抓取</strong><span style="font-size:24px">RSS / RSSHub 汇集候选信号</span><b style="font-size:32px;text-align:right">{stats["fetched"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid #bdbdb8;align-items:center"><strong style="font-size:28px">02 评分</strong><span style="font-size:24px">寻找具体关系、反常和结果</span><b style="font-size:32px;text-align:right">{stats["scored"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:1px solid #bdbdb8;align-items:center"><strong style="font-size:28px">03 筛选</strong><span style="font-size:24px">留下能形成玩家动作的材料</span><b style="font-size:32px;text-align:right">{stats["filtered"]}</b></div>
        <div style="display:grid;grid-template-columns:150px 1fr 90px;gap:22px;padding:28px 0;border-bottom:2px solid #202020;align-items:center"><strong style="font-size:28px">04 提炼</strong><span style="font-size:24px">新鲜关系与开放的游戏问题</span><b style="font-size:32px;text-align:right">{stats["enriched"]}</b></div>
      </div>
      <p class="lede" style="font-size:25px;margin-top:42px">每条创意线索只回答三件事：发生了什么、其中哪段关系真正新鲜、它可以打开哪类游戏问题。图片组展示 {len(featured)} 条，完整 Markdown 保留全部 {model["selected"]} 条。</p>
      <div class="footer"><span>RSSHub → Horizon → n8n</span><span>{date_label}</span></div>
    """
    cards.append(
        {
            "slug": "method",
            "html": _html_page(
                _shell(
                    method_content, accent="#171717", index=method_index, total=total
                ),
                accent="#171717",
                title="数据与方法",
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
    }
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
