"""Lightweight candidate evaluation and final editorial selection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from .client import AIClient
from .prompting.common import EVIDENCE_RULES, UNTRUSTED_INPUT_RULE
from .prompting.enrichment import item_context
from .utils import parse_json_response
from ..models import ContentItem
from ..processing.profiles import ProfileRegistry

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class CandidateEvaluation(BaseModel):
    factual_core: str
    fresh_relationship: str
    game_design_value: str
    evidence_quality: float = Field(ge=0, le=10)
    design_potential: float = Field(ge=0, le=10)
    visual_potential: float = Field(ge=0, le=10)
    novelty: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    rejection_risk: Optional[str] = None


class SelectedCandidate(BaseModel):
    id: str
    rank: int = Field(ge=1)
    reason: str


class SelectionDecision(BaseModel):
    selected: list[SelectedCandidate]
    summary: str


@dataclass
class EvaluationBatchResult:
    succeeded_ids: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.failures:
            return "success"
        return "partial_failure" if self.succeeded_ids else "failure"

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def failed_ids(self) -> list[str]:
        return list(self.failures)


def _evaluation_prompt(profile_context: str) -> str:
    return f"""You are preparing researched candidates for a later editorial jury.
Evaluate the material; do not write the final article.

{UNTRUSTED_INPUT_RULE}
{EVIDENCE_RULES}

Profile context:
{profile_context}

Return valid JSON only:
{{
  "factual_core": "the most decision-relevant verified event or behavior",
  "fresh_relationship": "the non-obvious relationship supported by the evidence",
  "game_design_value": "the concrete game-design value, without inventing a game pitch",
  "evidence_quality": 0-10,
  "design_potential": 0-10,
  "visual_potential": 0-10,
  "novelty": 0-10,
  "confidence": 0-1,
  "rejection_risk": "specific weakness or null"
}}

Keep the three text fields concise enough to compare across many candidates."""


def _selection_prompt(limit: int, min_topics: int, max_per_source: int) -> str:
    return f"""You are the final editorial jury for a game-inspiration radar.
Choose exactly {limit} candidates from the supplied researched evaluations.

Optimize the set, not isolated scores:
- evidence strength and factual specificity;
- a genuinely fresh relationship;
- concrete game-design usefulness;
- visual/report-card potential;
- diversity of mechanisms, subjects, content boards, and sources.

Hard constraints:
- Choose exactly {limit} unique IDs from the input.
- Cover at least {min_topics} distinct content boards when the input permits it.
- Use at most {max_per_source} items from the same feed/source when the input permits it.
- Avoid near-duplicate themes even when both have high scores.
- Do not select a weak candidate merely to satisfy diversity.

{UNTRUSTED_INPUT_RULE}
{EVIDENCE_RULES}

Return valid JSON only:
{{
  "selected": [
    {{"id": "exact candidate id", "rank": 1, "reason": "set-aware reason"}}
  ],
  "summary": "why this set is the strongest editorial package"
}}"""


class EditorialSelector:
    def __init__(self, ai_client: AIClient, profiles: ProfileRegistry):
        self.client = ai_client
        self.profiles = profiles

    def _concurrency(self) -> int:
        config = getattr(self.client, "config", None)
        return max(1, getattr(config, "enrichment_concurrency", 1))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    async def _complete(self, **kwargs: Any) -> str:
        return await self.client.complete(**kwargs)

    async def _complete_model(
        self,
        model: type[ModelT],
        *,
        system: str,
        user: str,
        validator: Callable[[ModelT], None] | None = None,
    ) -> ModelT:
        validation_error: Optional[Exception] = None
        for _ in range(2):
            response = await self._complete(
                system=system, user=user, temperature=0, max_tokens=8192
            )
            try:
                result = model.model_validate(parse_json_response(response))
                if validator:
                    validator(result)
                return result
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                user += f"\nReturn corrected JSON only. Validation error: {exc}."
        raise ValueError("Invalid editorial selection response") from validation_error

    async def evaluate_batch(self, items: list[ContentItem]) -> EvaluationBatchResult:
        semaphore = asyncio.Semaphore(self._concurrency())

        async def evaluate(item: ContentItem) -> tuple[str, Optional[Exception]]:
            async with semaphore:
                try:
                    profile = self.profiles.get(item.processing.classification.profile)
                    evaluation = await self._complete_model(
                        CandidateEvaluation,
                        system=_evaluation_prompt(profile.enrichment_prompt),
                        user=item_context(item, profile, include_content=True),
                    )
                    item.metadata["editorial_evaluation"] = evaluation.model_dump(
                        mode="json"
                    )
                    return item.id, None
                except Exception as exc:
                    logger.error("Error evaluating item %s: %s", item.id, exc)
                    return item.id, exc

        outcomes = await asyncio.gather(*(evaluate(item) for item in items))
        return EvaluationBatchResult(
            succeeded_ids=[item_id for item_id, exc in outcomes if exc is None],
            failures={
                item_id: f"{type(exc).__name__}: {exc}"
                for item_id, exc in outcomes
                if exc is not None
            },
        )

    async def select(
        self,
        items: list[ContentItem],
        *,
        limit: int = 10,
        min_topics: int = 4,
        max_per_source: int = 2,
    ) -> tuple[list[ContentItem], dict[str, Any]]:
        if len(items) <= limit:
            ordered = sorted(items, key=_deterministic_key, reverse=True)
            decision = {
                "selected": [
                    {"id": item.id, "rank": rank, "reason": "all eligible candidates retained"}
                    for rank, item in enumerate(ordered, start=1)
                ],
                "summary": "The eligible pool did not exceed the requested limit.",
                "method": "all_eligible",
            }
            return ordered, decision

        candidates = [_selection_payload(item) for item in items]
        item_by_id = {item.id: item for item in items}
        try:
            decision = await self._complete_model(
                SelectionDecision,
                system=_selection_prompt(limit, min_topics, max_per_source),
                user="Candidates:\n" + _json_dumps(candidates),
                validator=lambda value: _validate_selection(
                    value,
                    item_by_id,
                    limit=limit,
                    min_topics=min_topics,
                    max_per_source=max_per_source,
                ),
            )
        except ValueError:
            selected = _deterministic_selection(
                items,
                limit=limit,
                min_topics=min_topics,
                max_per_source=max_per_source,
            )
            decision = SelectionDecision(
                selected=[
                    SelectedCandidate(
                        id=item.id,
                        rank=rank,
                        reason="deterministic fallback after invalid AI jury output",
                    )
                    for rank, item in enumerate(selected, start=1)
                ],
                summary="AI output failed validation; a reproducible evidence-and-diversity fallback was used.",
            )
        selected_ids: list[str] = []
        reasons: dict[str, str] = {}
        for row in sorted(decision.selected, key=lambda value: value.rank):
            if row.id in item_by_id and row.id not in selected_ids:
                selected_ids.append(row.id)
                reasons[row.id] = row.reason
        if len(selected_ids) < limit:
            for item in sorted(items, key=_deterministic_key, reverse=True):
                if item.id not in selected_ids:
                    selected_ids.append(item.id)
                    reasons[item.id] = "deterministic fallback after incomplete AI selection"
                if len(selected_ids) == limit:
                    break
        selected_ids = selected_ids[:limit]
        payload = {
            "selected": [
                {"id": item_id, "rank": rank, "reason": reasons[item_id]}
                for rank, item_id in enumerate(selected_ids, start=1)
            ],
            "summary": decision.summary,
            "method": (
                "deterministic_fallback"
                if decision.summary.startswith("AI output failed validation")
                else "ai_jury"
            ),
            "constraints": {
                "limit": limit,
                "min_topics": min_topics,
                "max_per_source": max_per_source,
            },
        }
        return [item_by_id[item_id] for item_id in selected_ids], payload


def _selection_payload(item: ContentItem) -> dict[str, Any]:
    analysis = item.processing.analysis if item.processing else None
    classification = item.processing.classification if item.processing else None
    return {
        "id": item.id,
        "title": item.title,
        "source": item.metadata.get("feed_name") or item.source_type.value,
        "topic": classification.profile if classification else item.profile,
        "score": analysis.score if analysis else None,
        "analysis_reason": analysis.reason if analysis else "",
        "evaluation": item.metadata.get("editorial_evaluation", {}),
    }


def _deterministic_key(item: ContentItem) -> tuple[float, float, float, str]:
    analysis = item.processing.analysis if item.processing else None
    evaluation = item.metadata.get("editorial_evaluation", {})
    return (
        float(evaluation.get("design_potential", 0)),
        float(evaluation.get("evidence_quality", 0)),
        float(analysis.score if analysis and analysis.score is not None else 0),
        item.id,
    )


def _source(item: ContentItem) -> str:
    return str(item.metadata.get("feed_name") or item.source_type.value)


def _topic(item: ContentItem) -> str:
    if item.processing:
        return item.processing.classification.profile
    return item.profile or "other"


def _validate_selection(
    decision: SelectionDecision,
    item_by_id: dict[str, ContentItem],
    *,
    limit: int,
    min_topics: int,
    max_per_source: int,
) -> None:
    ids = [row.id for row in decision.selected]
    if len(ids) != limit or len(set(ids)) != limit:
        raise ValueError(f"selection must contain exactly {limit} unique IDs")
    unknown = set(ids) - set(item_by_id)
    if unknown:
        raise ValueError(f"selection contains unknown IDs: {sorted(unknown)}")
    selected = [item_by_id[item_id] for item_id in ids]
    available_topics = {_topic(item) for item in item_by_id.values()}
    required_topics = min(min_topics, len(available_topics), limit)
    if len({_topic(item) for item in selected}) < required_topics:
        raise ValueError(f"selection must cover {required_topics} content boards")
    source_capacity = sum(
        min(max_per_source, sum(_source(item) == source for item in item_by_id.values()))
        for source in {_source(item) for item in item_by_id.values()}
    )
    if source_capacity >= limit:
        counts = {
            source: sum(_source(item) == source for item in selected)
            for source in {_source(item) for item in selected}
        }
        if any(count > max_per_source for count in counts.values()):
            raise ValueError(f"selection exceeds max_per_source={max_per_source}")


def _deterministic_selection(
    items: list[ContentItem],
    *,
    limit: int,
    min_topics: int,
    max_per_source: int,
) -> list[ContentItem]:
    ordered = sorted(items, key=_deterministic_key, reverse=True)
    selected: list[ContentItem] = []
    source_counts: dict[str, int] = {}

    for topic in dict.fromkeys(_topic(item) for item in ordered):
        candidate = next(
            (
                item
                for item in ordered
                if _topic(item) == topic
                and source_counts.get(_source(item), 0) < max_per_source
            ),
            None,
        )
        if candidate and candidate not in selected:
            selected.append(candidate)
            source_counts[_source(candidate)] = source_counts.get(_source(candidate), 0) + 1
        if len({_topic(item) for item in selected}) >= min(min_topics, limit):
            break

    for enforce_cap in (True, False):
        for item in ordered:
            if item in selected:
                continue
            if enforce_cap and source_counts.get(_source(item), 0) >= max_per_source:
                continue
            selected.append(item)
            source_counts[_source(item)] = source_counts.get(_source(item), 0) + 1
            if len(selected) == limit:
                return selected
    return selected[:limit]


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
