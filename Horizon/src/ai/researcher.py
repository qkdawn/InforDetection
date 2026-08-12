"""Research selected items before profile-driven enrichment."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from tenacity import retry, stop_after_attempt, wait_exponential

from .client import AIClient
from .prompting.enrichment import item_context
from .utils import parse_json_response
from ..models import ContentItem
from ..processing.profiles import LoadedProfile, ProfileRegistry
from ..processing.tools import ToolRegistry

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)
# A runtime guard against a malformed plan; the prompt intentionally leaves the
# amount of research to the evidence needed for the selected focus.
MAX_RESEARCH_REQUESTS = 8


class ResearchRequest(BaseModel):
    kind: Literal["subject", "independent", "similar"]
    query: str
    purpose: str


class ResearchPlan(BaseModel):
    focus: str
    requests: list[ResearchRequest] = Field(default_factory=list)


@dataclass
class ResearchBatchResult:
    succeeded_ids: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded_count(self) -> int:
        return len(self.succeeded_ids)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def failed_ids(self) -> list[str]:
        return list(self.failures)

    @property
    def status(self) -> str:
        if not self.failures:
            return "success"
        if self.succeeded_ids:
            return "partial_failure"
        return "failure"


def research_prompt(profile: LoadedProfile) -> str:
    editorial_context = (
        f"""# Editorial stance

{profile.editorial_prompt}

"""
        if profile.editorial_prompt
        else ""
    )
    return f"""{editorial_context}# Background research

You are gathering reference material for a later editor. Do not write the final article or try to prove that extensive research was done. Listen to the source first, then ask which missing fact could genuinely change what is worth telling this audience.

Direction:
- Choose one focus that seems most worth understanding for the audience.
- Check the named subject itself first. Add an independent account or a close comparison only when it could confirm, correct, or complicate that understanding.
- Prefer concrete behavior and relationships over broad background.
- Stop when the source is already clear or another result would not change the editor's judgment.

The profile context is:
{profile.enrichment_prompt}

Return valid JSON only:
{{
  "focus": "<the one object or mechanism being researched>",
  "requests": [
    {{"kind": "subject" or "independent" or "similar", "query": "...", "purpose": "..."}}
  ]
}}
Use an empty list when the source already contains enough concrete evidence."""


class ContentResearcher:
    """Collect item-specific and mechanism-adjacent web references."""

    def __init__(
        self,
        ai_client: AIClient,
        profiles: ProfileRegistry,
        console: Optional[Console] = None,
        tools: Optional[ToolRegistry] = None,
    ):
        self.client = ai_client
        self.profiles = profiles
        self.console = console or Console(stderr=True)
        self.tools = tools or ToolRegistry()

    def _get_concurrency(self) -> int:
        config = getattr(self.client, "config", None)
        return max(getattr(config, "enrichment_concurrency", 1), 1)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    async def _complete(self, **kwargs: Any) -> str:
        return await self.client.complete(**kwargs)

    async def _complete_model(
        self,
        model: type[ModelT],
        *,
        system: str,
        user: str,
    ) -> ModelT:
        validation_error: Optional[Exception] = None
        for attempt in range(2):
            response = await self._complete(system=system, user=user, temperature=0)
            parsed = parse_json_response(response)
            try:
                return model.model_validate(parsed)
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                user += (
                    "\n\nReturn only a corrected JSON object. "
                    f"Validation error: {exc}."
                )
        raise ValueError("Invalid research plan") from validation_error

    async def research_batch(self, items: list[ContentItem]) -> ResearchBatchResult:
        semaphore = asyncio.Semaphore(self._get_concurrency())

        async def process(item: ContentItem, task_id: Any) -> tuple[str, Optional[Exception]]:
            async with semaphore:
                try:
                    await self._research_item(item)
                except Exception as exc:
                    logger.error("Error researching item %s: %s", item.id, exc)
                    return item.id, exc
                finally:
                    progress.advance(task_id)
            return item.id, None

        with Progress(
            SpinnerColumn(), TextColumn("Researching"), BarColumn(), MofNCompleteColumn(),
            transient=True, console=self.console,
        ) as progress:
            task_id = progress.add_task("Researching", total=len(items))
            outcomes = await asyncio.gather(*(process(item, task_id) for item in items))

        return ResearchBatchResult(
            succeeded_ids=[item_id for item_id, exc in outcomes if exc is None],
            failures={
                item_id: f"{type(exc).__name__}: {exc}"
                for item_id, exc in outcomes
                if exc is not None
            },
        )

    async def _research_item(self, item: ContentItem) -> None:
        if not item.processing or not item.processing.analysis:
            raise ValueError("Item must be analyzed before research")
        profile = self.profiles.get(item.processing.classification.profile)
        plan = await self._complete_model(
            ResearchPlan,
            system=research_prompt(profile),
            user=item_context(item, profile, include_content=True),
        )
        requests: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, request in enumerate(plan.requests[:MAX_RESEARCH_REQUESTS], start=1):
            query = request.query.strip()
            if not query or query.lower() in seen:
                continue
            seen.add(query.lower())
            result = await self.tools.execute(
                request_id=f"research-{index}",
                block_id="research",
                tool="web_search",
                arguments={"query": query},
            )
            requests.append(
                {
                    "kind": request.kind.strip().lower() or "subject",
                    "query": query,
                    "purpose": request.purpose.strip(),
                    "results": result.results,
                }
            )

        item.metadata["mechanism_research"] = {
            "status": "success" if any(request["results"] for request in requests) else "empty",
            "focus": plan.focus.strip(),
            "requests": requests,
        }
