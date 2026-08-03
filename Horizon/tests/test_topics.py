from __future__ import annotations

from pathlib import Path

from src.models import Config
from src.processing.profiles import ProfileRegistry
from src.topics import TopicRegistry, build_content_topic_profiles


ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    return Config.model_validate_json(
        (ROOT / "data/config.json").read_text(encoding="utf-8")
    )


def test_topic_catalog_shares_the_daily_and_x_source_pool() -> None:
    config = _config()
    registry = TopicRegistry.load(ROOT / "topics")

    described = registry.describe(config, "daily")

    assert [item["name"] for item in described] == [
        "玩法与机制",
        "世界与关卡",
        "叙事与文化",
        "视觉与体验",
        "玩家行为与市场",
        "技术与制作方法",
    ]
    assert {item["source_count"] for item in described} == {190}
    assert {item["routing"] for item in described} == {"content"}
    assert (
        sum(
            source.enabled and source.deployment_pool in {"daily", "x_watch"}
            for source in config.sources.rss
        )
        == 190
    )


def test_content_routing_preserves_account_categories_and_builds_topic_profiles() -> (
    None
):
    config = _config()
    registry = TopicRegistry.load(ROOT / "topics")

    effective = registry.apply_content_routing(config, "daily")
    base_profiles = ProfileRegistry.load(
        ROOT / "profiles", config.processing.default_profile
    )
    profiles = build_content_topic_profiles(base_profiles, registry.list("daily"))

    assert len(effective.sources.rss) == 190
    assert len({source.category for source in effective.sources.rss}) > 1
    assert {source.deployment_pool for source in effective.sources.rss} == {"daily"}
    assert {source.profile for source in effective.sources.rss} == {"auto"}
    assert profiles.ids == {
        "gameplay-mechanics",
        "world-level",
        "narrative-culture",
        "visual-experience",
        "player-market",
        "production-tech",
    }
    profile = profiles.get("gameplay-mechanics")
    assert "具体规则、行为、约束" in profile.match_prompt
    assert "独特的玩家参与关系" in profile.analysis_prompt
    assert "不要默认写成资源管理" in profile.enrichment_prompt
    assert "不要默认写成资源管理" not in profile.analysis_prompt
    assert profile.definition.filter.threshold == 7.0


def test_topic_folders_have_no_source_assignment_files() -> None:
    assert list((ROOT / "topics").glob("*/sources.json")) == []
