#!/usr/bin/env python3
"""Import the v2 game-inspiration source catalog into Horizon config."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse


LOCAL_RSSHUB_BASE = "http://rsshub:1200"
POOL_NAMES = {
    "Daily Core": "daily",
    "Weekly Discovery": "weekly",
    "Reserve": "reserve",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_rsshub_url(url: str, catalog_base: str) -> str:
    if catalog_base and url.startswith(catalog_base.rstrip("/")):
        return LOCAL_RSSHUB_BASE + url[len(catalog_base.rstrip("/")) :]
    host = urlparse(url).hostname or ""
    if host.endswith("run.app") and ("/reddit/" in url or "/twitter/" in url):
        parsed = urlparse(url)
        return LOCAL_RSSHUB_BASE + parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return url


def _validate_catalog(payload: dict) -> tuple[list[dict], list[dict]]:
    rss_sources = payload.get("rss_sources") or []
    x_accounts = payload.get("x_accounts") or []
    settings = payload.get("settings") or {}
    if len(rss_sources) != int(settings.get("rss_total") or 0):
        raise ValueError("rss_sources count does not match settings.rss_total")
    if len(x_accounts) != int(settings.get("x_total") or 0):
        raise ValueError("x_accounts count does not match settings.x_total")
    for label, rows in (("RSS", rss_sources), ("X", x_accounts)):
        ids = [str(row.get("id") or "") for row in rows]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError(f"{label} source IDs are missing or duplicated")
    return rss_sources, x_accounts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--catalog-copy", type=Path, required=True)
    args = parser.parse_args()

    payload = _load(args.catalog)
    config = _load(args.config)
    rss_sources, x_accounts = _validate_catalog(payload)
    catalog_base = str((payload.get("settings") or {}).get("rsshub_base") or "")

    operational_rss = [
        {
            "name": source["name"],
            "url": _normalize_rsshub_url(source["feed_url"], catalog_base),
            "enabled": True,
            "catalog_id": source["id"],
            "deployment_pool": POOL_NAMES[source["deployment_pool"]],
            "category": source["category"],
            "profile": "game-tech-daily",
        }
        for source in rss_sources
    ]
    operational_x = [
        {
            "name": f"X · {account['name']} ({account['handle']})",
            "url": _normalize_rsshub_url(account["rsshub_url"], catalog_base),
            "enabled": True,
            "catalog_id": account["id"],
            "deployment_pool": "x_watch",
            "category": account["category"],
            "profile": "game-tech-daily",
        }
        for account in x_accounts
    ]

    config["sources"]["rss"] = operational_rss + operational_x
    config["sources"]["twitter"] = {"enabled": False, "users": []}
    config.setdefault("collection", {})["default_source_pool"] = "daily"
    args.config.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.catalog_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.catalog, args.catalog_copy)

    print(
        json.dumps(
            {
                "rss_catalog": len(operational_rss),
                "rss_enabled": sum(1 for row in operational_rss if row["enabled"]),
                "x_watch": len(operational_x),
                "x_enabled": sum(1 for row in operational_x if row["enabled"]),
                "operational_total": len(config["sources"]["rss"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
