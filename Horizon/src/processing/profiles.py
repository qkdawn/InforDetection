"""Load processing profiles from JSON and Markdown files."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

BUILTIN_PROFILES_DIR = Path(__file__).resolve().parents[1] / "_builtin_profiles"


class ProfileFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    threshold: Optional[float] = Field(default=None, ge=0, le=10)

    @model_validator(mode="after")
    def require_threshold_when_enabled(self) -> "ProfileFilter":
        if self.enabled and self.threshold is None:
            raise ValueError("filter.threshold is required when filtering is enabled")
        return self


class ProfileContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_max_chars: int = Field(default=1000, ge=500, le=100_000)
    enrichment_max_chars: int = Field(default=8000, ge=500, le=100_000)
    sampling: Literal["prefix", "head-middle-tail"] = "prefix"


class ProfileTopicDedup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class ProfileBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    type: Literal["section"] = "section"
    tools: list[str] = Field(default_factory=list)
    optional: bool = False
    primary: bool = False


class ProfileEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    insight_block: Optional[str] = None
    systems_block: Optional[str] = None
    blocks: list[ProfileBlock] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_block_ids(self) -> "ProfileEnrichment":
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("enrichment block IDs must be unique")
        primary_blocks = [block for block in self.blocks if block.primary]
        if len(primary_blocks) > 1:
            raise ValueError("enrichment may define at most one primary block")
        if primary_blocks and primary_blocks[0].optional:
            raise ValueError("the primary enrichment block must be required")
        if self.insight_block:
            if self.insight_block not in ids:
                raise ValueError("enrichment.insight_block must name a configured block")
            insight_block = next(
                block for block in self.blocks if block.id == self.insight_block
            )
            if insight_block.primary:
                raise ValueError("enrichment.insight_block cannot be the primary block")
            if insight_block.optional:
                raise ValueError("enrichment.insight_block must be required")
        if self.systems_block:
            if self.systems_block not in ids:
                raise ValueError("enrichment.systems_block must name a configured block")
            systems_block = next(
                block for block in self.blocks if block.id == self.systems_block
            )
            if systems_block.primary:
                raise ValueError("enrichment.systems_block cannot be the primary block")
            if systems_block.optional:
                raise ValueError("enrichment.systems_block must be required")
            if self.systems_block == self.insight_block:
                raise ValueError(
                    "enrichment.systems_block must differ from insight_block"
                )
        return self


class ProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str
    display_names: dict[str, str] = Field(default_factory=dict)
    match: str
    analysis: str
    editorial: Optional[str] = None
    insight: Optional[str] = None
    systems: Optional[str] = None
    filter: ProfileFilter
    content: ProfileContent = Field(default_factory=ProfileContent)
    topic_dedup: ProfileTopicDedup = Field(default_factory=ProfileTopicDedup)
    enrichment: ProfileEnrichment

    @model_validator(mode="after")
    def require_complete_insight_configuration(self) -> "ProfileDefinition":
        if bool(self.insight) != bool(self.enrichment.insight_block):
            raise ValueError(
                "profile insight prompt and enrichment.insight_block must be configured together"
            )
        if bool(self.systems) != bool(self.enrichment.systems_block):
            raise ValueError(
                "profile systems prompt and enrichment.systems_block must be configured together"
            )
        if self.systems and not self.insight:
            raise ValueError("profile systems prompt requires an insight prompt")
        return self


@dataclass(frozen=True)
class LoadedProfile:
    definition: ProfileDefinition
    match_prompt: str
    analysis_prompt: str
    enrichment_prompt: str
    editorial_prompt: str = ""
    insight_prompt: str = ""
    systems_prompt: str = ""

    @property
    def id(self) -> str:
        return self.definition.id


class ProfileRegistry:
    """Validated profiles indexed by ID."""

    def __init__(self, profiles: dict[str, LoadedProfile], default_profile: str):
        if default_profile not in profiles:
            raise ValueError(f"Default profile does not exist: {default_profile}")
        self._profiles = profiles
        self.default_profile = default_profile

    @classmethod
    def load(
        cls,
        profiles_dir: Path,
        default_profile: str,
        *,
        base_dir: Optional[Path] = None,
    ) -> "ProfileRegistry":
        if profiles_dir.is_absolute():
            root = profiles_dir.resolve()
        else:
            root = ((base_dir or Path.cwd()) / profiles_dir).resolve()
            if (
                profiles_dir == Path("profiles")
                and not root.is_dir()
                and BUILTIN_PROFILES_DIR.is_dir()
            ):
                root = BUILTIN_PROFILES_DIR
        profiles: dict[str, LoadedProfile] = {}
        for config_path in sorted(root.glob("*/profile.json")):
            definition = ProfileDefinition.model_validate_json(
                config_path.read_text(encoding="utf-8")
            )
            if definition.id in profiles:
                raise ValueError(f"Duplicate profile ID: {definition.id}")
            profile_dir = config_path.parent.resolve()
            profiles[definition.id] = LoadedProfile(
                definition=definition,
                match_prompt=cls._read_prompt(profile_dir, definition.match),
                analysis_prompt=cls._read_prompt(profile_dir, definition.analysis),
                enrichment_prompt=cls._read_prompt(
                    profile_dir, definition.enrichment.prompt
                ),
                editorial_prompt=(
                    cls._read_prompt(profile_dir, definition.editorial)
                    if definition.editorial
                    else ""
                ),
                insight_prompt=(
                    cls._read_prompt(profile_dir, definition.insight)
                    if definition.insight
                    else ""
                ),
                systems_prompt=(
                    cls._read_prompt(profile_dir, definition.systems)
                    if definition.systems
                    else ""
                ),
            )
        if not profiles:
            raise ValueError(f"No profiles found under {root}")
        return cls(profiles, default_profile)

    @staticmethod
    def _read_prompt(profile_dir: Path, relative_path: str) -> str:
        path = (profile_dir / relative_path).resolve()
        if not path.is_relative_to(profile_dir):
            raise ValueError(f"Prompt path escapes profile directory: {relative_path}")
        return path.read_text(encoding="utf-8").strip()

    def get(self, profile_id: str) -> LoadedProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"Unknown processing profile: {profile_id}") from exc

    def validate_source_references(self, value: object) -> None:
        """Reject unknown explicit profile IDs anywhere in source config."""
        if isinstance(value, dict):
            requested = value.get("profile")
            if isinstance(requested, str):
                normalized = requested.strip()
                if normalized and normalized != "auto":
                    self.get(normalized)
            for child in value.values():
                self.validate_source_references(child)
        elif isinstance(value, list):
            for child in value:
                self.validate_source_references(child)

    @property
    def ids(self) -> set[str]:
        return set(self._profiles)

    @property
    def profiles(self) -> tuple[LoadedProfile, ...]:
        return tuple(self._profiles.values())

    @property
    def names(self) -> dict[str, dict[str, str]]:
        return {
            profile_id: {
                "default": profile.definition.name,
                **profile.definition.display_names,
            }
            for profile_id, profile in self._profiles.items()
        }
