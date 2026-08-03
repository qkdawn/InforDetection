"""Resolve processing profiles for fetched content."""

import logging

from pydantic import BaseModel, Field, ValidationError

from .client import AIClient
from .prompting.classification import (
    classification_system_prompt,
    classification_user_prompt,
)
from .utils import parse_json_response
from ..models import ClassificationResult, ContentItem, ProcessingResult
from ..processing.profiles import LoadedProfile, ProfileRegistry

logger = logging.getLogger(__name__)


class ClassificationResponse(BaseModel):
    profile: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class ContentClassifier:
    """Choose a profile from explicit source configuration or AI matching."""

    def __init__(self, client: AIClient, profiles: ProfileRegistry):
        self.client = client
        self.profiles = profiles

    async def resolve(self, item: ContentItem) -> LoadedProfile:
        requested = (item.profile or "auto").strip()
        if (
            item.processing
            and item.processing.classification.method == "ai_match"
            and (
                requested == "auto"
                or requested == item.processing.classification.profile
            )
        ):
            return self.profiles.get(item.processing.classification.profile)
        if requested and requested != "auto":
            profile = self.profiles.get(requested)
            classification = ClassificationResult(
                profile=profile.id,
                method="source_override",
            )
            if item.processing is None:
                item.processing = ProcessingResult(classification=classification)
            else:
                profile_changed = item.processing.classification.profile != profile.id
                item.processing.classification = classification
                if profile_changed:
                    item.processing.analysis = None
                    item.processing.artifacts.clear()
            return profile

        try:
            result = await self._classify(item)
            profile = self.profiles.get(result.profile)
            classification = ClassificationResult(
                profile=profile.id,
                method="ai_match",
                confidence=result.confidence,
                reason=result.reason,
            )
        except Exception as exc:
            logger.warning(
                "Could not classify %s: %s",
                item.id,
                exc,
            )
            raise RuntimeError(f"Content classification failed: {exc}") from exc

        item.processing = ProcessingResult(classification=classification)
        return profile

    async def _classify(self, item: ContentItem) -> ClassificationResponse:
        response = await self.client.complete(
            system=classification_system_prompt(),
            user=classification_user_prompt(item, self.profiles),
        )
        parsed = parse_json_response(response)
        if not isinstance(parsed, dict):
            raise ValueError("classifier did not return an object")
        try:
            result = ClassificationResponse.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("invalid classifier response") from exc
        if result.profile not in self.profiles.ids:
            raise ValueError(f"classifier selected unknown profile: {result.profile}")
        return result
