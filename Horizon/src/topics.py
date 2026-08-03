"""Configuration-driven topic folders for isolated Horizon runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .processing.profiles import LoadedProfile, ProfileRegistry


Cadence = Literal["daily", "weekly", "reserve"]
SourcePool = Literal["daily", "weekly", "reserve", "x_watch"]


class TopicDefinition(BaseModel):
    """Topic metadata and run policy loaded from ``topic.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str = Field(min_length=1)
    enabled: bool = True
    order: int = 100
    color: str = Field(default="#4b5563", pattern=r"^#[0-9A-Fa-f]{6}$")
    profile: str = Field(default="game-tech-daily", pattern=r"^[a-z][a-z0-9_-]*$")
    min_score: float = Field(default=7.0, ge=0, le=10)
    cadences: dict[Cadence, list[SourcePool]] = Field(default_factory=dict)

    @field_validator("cadences")
    @classmethod
    def require_unique_pools(
        cls, value: dict[Cadence, list[SourcePool]]
    ) -> dict[Cadence, list[SourcePool]]:
        for cadence, pools in value.items():
            if len(pools) != len(set(pools)):
                raise ValueError(f"duplicate source pool in cadence {cadence}")
        return value


@dataclass(frozen=True)
class TopicBundle:
    """Validated topic folder and its stage-specific prompts."""

    definition: TopicDefinition
    match_prompt: str
    analysis_prompt: str
    enrichment_prompt: str
    path: Path

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def name(self) -> str:
        return self.definition.name

    def supports(self, cadence: str) -> bool:
        return bool(self.definition.cadences.get(cadence, []))


class TopicRegistry:
    """Discover topics from folders without hard-coding boards in application code."""

    def __init__(self, topics: dict[str, TopicBundle], root: Path):
        self._topics = topics
        self.root = root

    @classmethod
    def load(cls, root: Path) -> "TopicRegistry":
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f"Topics directory does not exist: {root}")

        topics: dict[str, TopicBundle] = {}
        for topic_path in sorted(path for path in root.iterdir() if path.is_dir()):
            definition_path = topic_path / "topic.json"
            if not definition_path.exists():
                continue
            definition = TopicDefinition.model_validate_json(
                definition_path.read_text(encoding="utf-8")
            )
            if definition.id != topic_path.name:
                raise ValueError(
                    f"Topic folder {topic_path.name!r} must match id {definition.id!r}"
                )
            if definition.id in topics:
                raise ValueError(f"Duplicate topic ID: {definition.id}")

            prompts = {}
            for stage in ("match", "analysis", "enrichment"):
                prompt_path = topic_path / f"{stage}.md"
                if not prompt_path.exists():
                    raise ValueError(f"Topic {definition.id} is missing {stage}.md")
                prompt = prompt_path.read_text(encoding="utf-8").strip()
                if not prompt:
                    raise ValueError(f"Topic {definition.id} has an empty {stage}.md")
                prompts[stage] = prompt

            topics[definition.id] = TopicBundle(
                definition=definition,
                match_prompt=prompts["match"],
                analysis_prompt=prompts["analysis"],
                enrichment_prompt=prompts["enrichment"],
                path=topic_path.resolve(),
            )

        if not topics:
            raise ValueError(f"No topic folders found under {root}")
        return cls(topics, root)

    def list(self, cadence: str | None = None) -> list[TopicBundle]:
        topics = [topic for topic in self._topics.values() if topic.definition.enabled]
        if cadence is not None:
            topics = [topic for topic in topics if topic.supports(cadence)]
        return sorted(topics, key=lambda topic: (topic.definition.order, topic.id))

    def describe(self, config: Any, cadence: str) -> list[dict[str, Any]]:
        shared_source_count = len(self.select_cadence_sources(config, cadence))
        return [
            {
                "id": topic.id,
                "name": topic.name,
                "order": topic.definition.order,
                "color": topic.definition.color,
                "profile": topic.definition.profile,
                "min_score": topic.definition.min_score,
                "cadence": cadence,
                "hours": {"daily": 24, "weekly": 168, "reserve": 720}[cadence],
                "source_pools": topic.definition.cadences[cadence],
                "source_count": shared_source_count,
                "routing": "content",
            }
            for topic in self.list(cadence)
        ]

    def source_pools(self, cadence: str) -> set[SourcePool]:
        pools: set[SourcePool] = set()
        for topic in self.list(cadence):
            pools.update(topic.definition.cadences.get(cadence, []))
        return pools

    def select_cadence_sources(self, config: Any, cadence: str) -> list[Any]:
        """Select the shared account pool before item-level topic routing."""

        pools = self.source_pools(cadence)
        return [
            source
            for source in getattr(getattr(config, "sources", None), "rss", [])
            if source.enabled and source.deployment_pool in pools
        ]

    def apply_content_routing(self, config: Any, cadence: str) -> Any:
        """Prepare one shared fetch whose items are routed by their own content."""

        selected = self.select_cadence_sources(config, cadence)
        topics = self.list(cadence)
        if not topics:
            raise ValueError(f"No enabled topics support cadence {cadence}")

        effective = config.model_copy(deep=True)
        effective.sources.rss = [source.model_copy(deep=True) for source in selected]
        for source in effective.sources.rss:
            source.deployment_pool = "daily"
            source.profile = "auto"
        effective.collection.default_source_pool = "daily"
        effective.digest.category_groups = {}
        effective.processing.default_profile = topics[0].id
        return effective


def build_content_topic_profiles(
    base: ProfileRegistry, topics: list[TopicBundle]
) -> ProfileRegistry:
    """Build one processing profile per content topic for AI item routing."""

    replacements: dict[str, LoadedProfile] = {}
    for topic in topics:
        selected = base.get(topic.definition.profile)
        definition = selected.definition.model_copy(deep=True)
        definition.id = topic.id
        definition.name = topic.name
        definition.display_names = {**definition.display_names, "zh": topic.name}
        definition.filter.threshold = topic.definition.min_score
        replacements[topic.id] = LoadedProfile(
            definition=definition,
            match_prompt=(
                f"{selected.match_prompt}\n\n"
                f"# Content board: {topic.name}\n\n{topic.match_prompt}"
            ),
            analysis_prompt=(
                f"{selected.analysis_prompt}\n\n"
                f"# Board value: {topic.name}\n\n{topic.analysis_prompt}"
            ),
            enrichment_prompt=(
                f"{selected.enrichment_prompt}\n\n"
                f"# Board enrichment: {topic.name}\n\n{topic.enrichment_prompt}"
            ),
        )

    if not replacements:
        raise ValueError("At least one content topic is required")
    return ProfileRegistry(replacements, topics[0].id)


def topic_manifest(topic: TopicBundle) -> dict[str, Any]:
    """Return JSON-safe topic metadata for run artifacts and reports."""

    return json.loads(topic.definition.model_dump_json())
