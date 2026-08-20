from __future__ import annotations

import json
from pathlib import Path

from src.models import Config


ROOT = Path(__file__).resolve().parents[1]


def test_v2_source_catalog_is_deployed_consistently():
    catalog = json.loads(
        (ROOT / "data/game-inspiration-radar-sources-v2.json").read_text(
            encoding="utf-8"
        )
    )
    config_payload = json.loads(
        (ROOT / "data/config.json").read_text(encoding="utf-8")
    )
    config = Config.model_validate(config_payload)

    assert len(catalog["rss_sources"]) == 300
    assert len(catalog["x_accounts"]) == 100
    assert len(config.sources.rss) == 400
    assert sum(source.enabled for source in config.sources.rss) == 400
    assert all(
        source.enabled
        for source in config.sources.rss
        if source.name.startswith("X · ")
    )
    assert all(source.profile == "game-tech-daily" for source in config.sources.rss)
    assert config.collection.default_source_pool == "daily"
    assert {
        pool: sum(
            source.enabled and source.deployment_pool == pool
            for source in config.sources.rss
        )
        for pool in ("daily", "weekly", "reserve", "x_watch")
    } == {"daily": 94, "weekly": 130, "reserve": 80, "x_watch": 96}
    assert all(
        "dawnqk-sc5qu5z4da-de.a.run.app" not in str(source.url)
        for source in config.sources.rss
    )
