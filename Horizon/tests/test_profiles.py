import json
import shutil
from pathlib import Path

import pytest

import src.processing.profiles as profile_module
from src.processing import ProfileRegistry


def test_loads_builtin_profiles():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )

    for profile_id in ("tech-news", "tech-blog"):
        profile = registry.get(profile_id)
        assert profile.match_prompt
        assert profile.analysis_prompt
        assert profile.enrichment_prompt


def test_game_inspiration_profile_requires_playable_depth():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "game-tech-daily"
    )
    profile = registry.get("game-tech-daily")

    assert [block.id for block in profile.definition.enrichment.blocks] == [
        "what_happened",
        "fresh_relationship",
        "game_question",
    ]
    assert "真正新鲜的关系是什么" in profile.enrichment_prompt
    assert "它可能启发哪一类游戏问题" in profile.enrichment_prompt
    assert "不要把问题写成答案" in profile.enrichment_prompt
    assert "不替它设计角色" in profile.enrichment_prompt
    assert "why_playable" not in profile.enrichment_prompt
    assert "player_choices" not in profile.enrichment_prompt
    assert "first_test" not in profile.enrichment_prompt
    assert "brief observation can be excellent" in profile.analysis_prompt
    assert "core relationship" in profile.analysis_prompt
    assert (
        "scientific, commercial, or cultural interest alone is not enough"
        in profile.analysis_prompt
    )
    assert (
        "Count only relationships stated in the supplied item"
        in profile.analysis_prompt
    )
    assert "Do not inventory routine omissions" in profile.analysis_prompt
    assert (
        "Mention missing information only when it materially caps"
        in profile.analysis_prompt
    )
    assert "不要为了显得严谨而补写" in profile.enrichment_prompt
    assert "不在段末追加" in profile.enrichment_prompt
    assert "包括主体、条件、结果和仍不确定之处" not in profile.enrichment_prompt
    assert profile.definition.filter.threshold == 7.0


def test_default_profiles_fall_back_to_packaged_resources(tmp_path, monkeypatch):
    packaged_profiles = tmp_path / "packaged-profiles"
    source_profiles = Path(__file__).resolve().parents[1] / "profiles"
    shutil.copytree(source_profiles, packaged_profiles)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(profile_module, "BUILTIN_PROFILES_DIR", packaged_profiles)

    registry = ProfileRegistry.load(Path("profiles"), "tech-news")

    assert registry.get("tech-news").analysis_prompt


def test_rejects_enabled_filter_without_threshold(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    for name in ("match.md", "analysis.md", "enrichment.md"):
        (profile_dir / name).write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "match.md",
                "analysis": "analysis.md",
                "filter": {"enabled": True},
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="threshold"):
        ProfileRegistry.load(tmp_path, "invalid")


def test_rejects_prompt_path_outside_profile_directory(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    (tmp_path / "outside.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "analysis.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "enrichment.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "../outside.md",
                "analysis": "analysis.md",
                "filter": {"enabled": False},
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes"):
        ProfileRegistry.load(tmp_path, "invalid")
