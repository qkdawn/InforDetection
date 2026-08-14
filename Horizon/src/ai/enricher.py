"""Profile-driven content enrichment."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from .client import AIClient
from .localization import normalize_language
from .prompting.enrichment import (
    MAX_SOURCE_READ_REQUESTS,
    MAX_TOOL_REQUESTS,
    artifact_prompt,
    block_prompt,
    editorial_tool_results_text,
    event_narration_prompt,
    game_insight_prompt,
    item_brief_context,
    item_context,
    source_read_planning_prompt,
    systems_question_prompt,
    tool_planning_prompt,
    tool_results_text,
)
from .utils import parse_json_response
from ..models import ArtifactSource, ContentArtifact, ContentBlock, ContentItem
from ..processing.profiles import LoadedProfile, ProfileBlock, ProfileRegistry
from ..processing.content import select_content, select_matching_content, split_content
from ..processing.tools import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

class ToolRequest(BaseModel):
    block_id: str
    tool: str
    arguments: dict[str, Any]
    purpose: str


class ToolPlan(BaseModel):
    tool_requests: list[ToolRequest] = Field(default_factory=list)


class SourceReadArguments(BaseModel):
    mode: Literal["sample", "search"]
    terms: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_arguments(self) -> "SourceReadArguments":
        if self.mode == "sample" and self.terms:
            raise ValueError("sample source reads must not include terms")
        if self.mode == "search" and not any(term.strip() for term in self.terms):
            raise ValueError("search source reads require at least one term")
        return self


class SourceReadRequest(BaseModel):
    tool: Literal["read_source"]
    arguments: SourceReadArguments
    purpose: str

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source read purpose must not be empty")
        return value


class SourceReadPlan(BaseModel):
    tool_requests: list[SourceReadRequest] = Field(
        min_length=1,
        max_length=MAX_SOURCE_READ_REQUESTS,
    )


class GeneratedArtifact(BaseModel):
    title: str
    blocks: list[ContentBlock]

    @model_validator(mode="after")
    def validate_non_empty_content(self) -> "GeneratedArtifact":
        if not self.title.strip():
            raise ValueError("title must not be empty")
        for block in self.blocks:
            if not block.title.strip() or not block.content.strip():
                raise ValueError(f"block {block.id} must not be empty")
        return self


class GeneratedBlock(BaseModel):
    title: str = ""
    block: Optional[ContentBlock] = None

    @model_validator(mode="after")
    def validate_non_empty_block(self) -> "GeneratedBlock":
        if self.block and (
            not self.block.title.strip() or not self.block.content.strip()
        ):
            raise ValueError(f"block {self.block.id} must not be empty")
        return self


class GeneratedBlockWithHeader(GeneratedBlock):
    @field_validator("title")
    @classmethod
    def validate_non_empty_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class GeneratedInsight(BaseModel):
    decision: Literal["publish", "reject"]
    insight: Optional[ContentBlock] = None
    rejection_reason: str = ""

    @model_validator(mode="after")
    def validate_decision(self) -> "GeneratedInsight":
        if self.decision == "publish":
            if self.insight is None:
                raise ValueError("publish requires an insight")
            if not self.insight.title.strip() or not self.insight.content.strip():
                raise ValueError("published insight must not be empty")
            if self.rejection_reason.strip():
                raise ValueError("publish must not include a rejection reason")
        else:
            if self.insight is not None:
                raise ValueError("reject must not include an insight")
            if not self.rejection_reason.strip():
                raise ValueError("reject requires a rejection reason")
        return self


class GeneratedSystemsQuestion(BaseModel):
    question: ContentBlock

    @model_validator(mode="after")
    def validate_question(self) -> "GeneratedSystemsQuestion":
        if not self.question.title.strip() or not self.question.content.strip():
            raise ValueError("systems question must not be empty")
        return self


class EnrichmentRejected(Exception):
    """A valid editorial decision that excludes an item from publication."""

    def __init__(self, reason: str):
        self.reason = reason.strip()
        super().__init__(self.reason)


@dataclass
class EnrichmentBatchResult:
    succeeded_ids: list[str] = field(default_factory=list)
    rejections: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded_count(self) -> int:
        return len(self.succeeded_ids)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections)

    @property
    def rejected_ids(self) -> list[str]:
        return list(self.rejections)

    @property
    def failed_ids(self) -> list[str]:
        return list(self.failures)

    @property
    def status(self) -> str:
        if self.failures and (self.succeeded_ids or self.rejections):
            return "partial_failure"
        if self.failures:
            return "failure"
        return "success"


class ContentEnricher:
    """Generate localized block artifacts with profile-scoped tools."""

    def __init__(
        self,
        ai_client: AIClient,
        profiles: ProfileRegistry,
        languages: list[str],
        console: Optional[Console] = None,
        tools: Optional[ToolRegistry] = None,
    ):
        self.client = ai_client
        self.profiles = profiles
        self.languages = languages
        self.console = console or Console(stderr=True)
        self.tools = tools or ToolRegistry()
        self._validate_profile_tools()

    def _validate_profile_tools(self) -> None:
        for profile_id in self.profiles.ids:
            profile = self.profiles.get(profile_id)
            for block in profile.definition.enrichment.blocks:
                unknown = set(block.tools) - self.tools.names
                if unknown:
                    raise ValueError(
                        f"Profile {profile_id} block {block.id} uses unknown tools: "
                        f"{', '.join(sorted(unknown))}"
                    )

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
        error_message: str,
        validator: Optional[Callable[[ModelT], None]] = None,
    ) -> ModelT:
        validation_error: Optional[Exception] = None
        for attempt in range(2):
            request: dict[str, Any] = {
                "system": system,
                "user": user,
                "temperature": 0,
            }
            response = await self._complete(**request)
            parsed = parse_json_response(response)
            try:
                result = model.model_validate(parsed)
                if validator:
                    validator(result)
                return result
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                user += (
                    "\n\nYour previous response did not satisfy the output contract. "
                    f"Validation error: {exc}. Return only a corrected JSON object."
                )
        raise ValueError(error_message) from validation_error

    async def enrich_batch(self, items: list[ContentItem]) -> EnrichmentBatchResult:
        semaphore = asyncio.Semaphore(self._get_concurrency())

        async def process(
            item: ContentItem, task_id: TaskID
        ) -> tuple[str, Optional[Exception], Optional[str]]:
            async with semaphore:
                try:
                    await self._enrich_item(item)
                except EnrichmentRejected as exc:
                    logger.info("Editorially rejected item %s: %s", item.id, exc.reason)
                    return item.id, None, exc.reason
                except Exception as exc:
                    logger.error("Error enriching item %s: %s", item.id, exc)
                    return item.id, exc, None
                finally:
                    progress.advance(task_id)
            return item.id, None, None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
            console=self.console,
        ) as progress:
            task_id = progress.add_task("Enriching", total=len(items))
            outcomes = await asyncio.gather(*(process(item, task_id) for item in items))

        return EnrichmentBatchResult(
            succeeded_ids=[
                item_id
                for item_id, exc, rejection in outcomes
                if exc is None and rejection is None
            ],
            rejections={
                item_id: rejection
                for item_id, exc, rejection in outcomes
                if exc is None and rejection is not None
            },
            failures={
                item_id: f"{type(exc).__name__}: {exc}"
                for item_id, exc, rejection in outcomes
                if exc is not None
            },
        )

    async def _enrich_item(self, item: ContentItem) -> None:
        if not item.processing or not item.processing.analysis:
            raise ValueError("Item must be analyzed before enrichment")
        profile = self.profiles.get(item.processing.classification.profile)
        for language in self.languages:
            item.processing.artifacts.pop(language, None)
        tool_results = await self._plan_and_execute_tools(item, profile)
        sources = self._sources_from_tool_results(tool_results)

        artifacts = {}
        for language in self.languages:
            generated = await self._generate_artifact(
                item, profile, language, tool_results
            )
            self._expand_request_source_refs(generated.blocks, tool_results)
            self._validate_blocks(generated.blocks, profile, tool_results)
            generated.title = normalize_language(generated.title, language)
            for block in generated.blocks:
                block.title = normalize_language(block.title, language)
                block.content = normalize_language(block.content, language)
            referenced = {
                source_id
                for block in generated.blocks
                for source_id in block.source_refs
            }
            artifacts[language] = ContentArtifact(
                language=language,
                title=generated.title,
                blocks=generated.blocks,
                sources=[source for source in sources.values() if source.id in referenced],
            )
        item.processing.artifacts.update(artifacts)

    @staticmethod
    def _expand_request_source_refs(
        blocks: list[ContentBlock],
        tool_results: list[ToolResult],
    ) -> None:
        """Expand a request-level citation to its concrete result citations."""
        request_sources = {
            (result.block_id, result.request_id): [
                f"{result.request_id}-{index}"
                for index, _ in enumerate(result.results, start=1)
            ]
            for result in tool_results
        }
        for block in blocks:
            expanded = []
            for source_ref in block.source_refs:
                expanded.extend(
                    request_sources.get((block.id, source_ref), [source_ref])
                )
            block.source_refs = list(dict.fromkeys(expanded))

    async def _plan_and_execute_tools(
        self, item: ContentItem, profile: LoadedProfile
    ) -> list[ToolResult]:
        allowed = {
            block.id: set(block.tools)
            for block in profile.definition.enrichment.blocks
        }
        if not any(allowed.values()):
            return []

        preloaded = self._research_tool_results(item, profile)

        plan = await self._complete_model(
            ToolPlan,
            system=tool_planning_prompt(
                profile, profile.definition.enrichment.blocks
            ),
            user=item_context(item, profile, include_content=True),
            error_message="Invalid enrichment tool plan",
        )

        results = list(preloaded)
        seen = set()
        for request in plan.tool_requests[:MAX_TOOL_REQUESTS]:
            if request.block_id not in allowed:
                raise ValueError(f"Tool request targets unknown block: {request.block_id}")
            if request.tool not in allowed[request.block_id]:
                raise ValueError(
                    f"Tool {request.tool} is not allowed for block {request.block_id}"
                )
            key = (request.block_id, request.tool, json.dumps(request.arguments, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                await self.tools.execute(
                    request_id=f"tool-{len(results) + 1}",
                    block_id=request.block_id,
                    tool=request.tool,
                    arguments=request.arguments,
                )
            )
        return results

    @staticmethod
    def _research_tool_results(
        item: ContentItem, profile: LoadedProfile
    ) -> list[ToolResult]:
        """Expose the independent research stage as citation-ready tool results."""
        research = item.metadata.get("mechanism_research")
        if not isinstance(research, dict):
            return []
        requests = research.get("requests")
        if not isinstance(requests, list):
            return []
        results: list[ToolResult] = []
        for block in profile.definition.enrichment.blocks:
            if "web_search" not in block.tools:
                continue
            for index, request in enumerate(requests, start=1):
                if not isinstance(request, dict) or not isinstance(request.get("results"), list):
                    continue
                entries = [
                    {
                        "title": str(entry.get("title", "")),
                        "url": str(entry.get("url", "")),
                        "text": str(entry.get("text", "")),
                    }
                    for entry in request["results"]
                    if isinstance(entry, dict) and entry.get("url")
                ]
                if entries:
                    results.append(
                        ToolResult(
                            request_id=f"research-{block.id}-{index}",
                            block_id=block.id,
                            tool="web_search",
                            results=entries,
                        )
                    )
        return results

    async def _generate_artifact(
        self,
        item: ContentItem,
        profile: LoadedProfile,
        language: str,
        tool_results: list[ToolResult],
    ) -> GeneratedArtifact:
        configured_blocks = profile.definition.enrichment.blocks
        if profile.insight_prompt:
            return await self._generate_editorial_artifact(
                item, profile, language, tool_results
            )

        result_block_ids = {result.block_id for result in tool_results}
        base_blocks = [
            block for block in configured_blocks if block.id not in result_block_ids
        ]
        title = ""
        generated_by_id: dict[str, ContentBlock] = {}

        if base_blocks:
            required_base_ids = {
                block.id for block in base_blocks if not block.optional
            }
            allowed_base_ids = {block.id for block in base_blocks}

            def validate_required_blocks(generated: GeneratedArtifact) -> None:
                generated_ids = [block.id for block in generated.blocks]
                unknown = set(generated_ids) - allowed_base_ids
                if unknown:
                    raise ValueError(
                        "unknown blocks: " + ", ".join(sorted(unknown))
                    )
                if len(generated_ids) != len(set(generated_ids)):
                    raise ValueError("duplicate block IDs")
                missing = required_base_ids - set(generated_ids)
                if missing:
                    raise ValueError(
                        "missing required blocks: " + ", ".join(sorted(missing))
                    )

            generated = await self._complete_model(
                GeneratedArtifact,
                system=artifact_prompt(profile, language, base_blocks),
                user=(
                    item_context(item, profile, include_content=True)
                    + "\n\n# Tool results\n\nNo tool results are available to these blocks."
                ),
                error_message="Invalid enrichment artifact",
                validator=validate_required_blocks,
            )
            title = generated.title.strip()
            allowed_ids = {block.id for block in base_blocks}
            configured_ids = {block.id for block in configured_blocks}
            for generated_block in generated.blocks:
                if generated_block.id not in allowed_ids:
                    if generated_block.id in configured_ids:
                        continue
                    raise ValueError(
                        f"Artifact contains unknown block: {generated_block.id}"
                    )
                if generated_block.id in generated_by_id:
                    raise ValueError(
                        f"Artifact contains duplicate block: {generated_block.id}"
                    )
                generated_by_id[generated_block.id] = generated_block
            missing = {
                block.id
                for block in base_blocks
                if not block.optional and block.id not in generated_by_id
            }
            if missing:
                raise ValueError(
                    f"Artifact is missing required blocks: {', '.join(sorted(missing))}"
                )

        for block in configured_blocks:
            if block.id not in result_block_ids:
                continue
            block_results = [
                result for result in tool_results if result.block_id == block.id
            ]
            response_model = GeneratedBlockWithHeader if not title else GeneratedBlock

            def validate_requested_block(generated: GeneratedBlock) -> None:
                if generated.block is None:
                    if not block.optional:
                        raise ValueError(f"missing required block: {block.id}")
                    return
                if generated.block.id != block.id:
                    raise ValueError(
                        f"block ID {generated.block.id} does not match {block.id}"
                    )

            generated = await self._complete_model(
                response_model,
                system=block_prompt(
                    profile,
                    language,
                    block,
                    include_header=not title,
                ),
                user=(
                    item_context(item, profile, include_content=True)
                    + f"\n\n# Tool results for block `{block.id}`\n\n"
                    + tool_results_text(block_results)
                ),
                error_message=f"Invalid enrichment block: {block.id}",
                validator=validate_requested_block,
            )

            if not title:
                title = generated.title.strip()
            if generated.block is None:
                if not block.optional:
                    raise ValueError(f"Artifact is missing required block: {block.id}")
                continue
            if generated.block.id != block.id:
                raise ValueError(
                    f"Artifact block {generated.block.id} does not match requested block {block.id}"
                )
            generated_by_id[block.id] = generated.block

        if not title:
            raise ValueError("Enrichment artifact title cannot be empty")
        blocks = [
            generated_by_id[block.id]
            for block in configured_blocks
            if block.id in generated_by_id
        ]
        configured_by_id = {block.id: block for block in configured_blocks}
        for generated_block in blocks:
            generated_block.primary = configured_by_id[generated_block.id].primary
        return GeneratedArtifact(title=title, blocks=blocks)

    async def _generate_editorial_artifact(
        self,
        item: ContentItem,
        profile: LoadedProfile,
        language: str,
        tool_results: list[ToolResult],
    ) -> GeneratedArtifact:
        configured_blocks = profile.definition.enrichment.blocks
        event_blocks = [block for block in configured_blocks if block.primary]
        if len(event_blocks) != 1:
            raise ValueError("Editorial two-pass generation requires one primary event block")
        event_block = event_blocks[0]
        insight_block_id = profile.definition.enrichment.insight_block
        if not insight_block_id:
            raise ValueError("Editorial two-pass generation requires an insight block")
        configured_by_id = {block.id: block for block in configured_blocks}
        insight_block = configured_by_id[insight_block_id]
        systems_block = None
        if profile.systems_prompt:
            systems_block_id = profile.definition.enrichment.systems_block
            if not systems_block_id:
                raise ValueError(
                    "Editorial staged generation requires a systems question block"
                )
            systems_block = configured_by_id[systems_block_id]
        reference_text = editorial_tool_results_text(tool_results)
        event_generated = await self._complete_model(
            GeneratedBlockWithHeader,
            system=event_narration_prompt(profile, language, event_block),
            user=(
                item_context(
                    item,
                    profile,
                    include_content=True,
                    include_research=False,
                )
                + "\n\n# Collected reference results\n\n"
                + reference_text
            ),
            error_message="Invalid event narration artifact",
            validator=lambda generated: self._validate_event_block(
                generated, event_block.id
            ),
        )

        event = event_generated.block
        if event is None:
            raise ValueError("Event narration must include the required event block")
        event.primary = event_block.primary

        source_plan = await self._complete_model(
            SourceReadPlan,
            system=source_read_planning_prompt(profile, language),
            user=(
                item_brief_context(item)
                + "\n\n# Event narration from the first editor\n\n"
                + json.dumps(
                    {
                        "title": event_generated.title,
                        "content": event.content,
                    },
                    ensure_ascii=False,
                )
            ),
            error_message="Invalid source read plan",
        )
        source_read_results = self._read_source(
            item,
            profile,
            source_plan.tool_requests,
        )

        insight_generated = await self._complete_model(
            GeneratedInsight,
            system=game_insight_prompt(profile, language, insight_block),
            user=(
                item_brief_context(item)
                + "\n\n# Event narration from the first editor\n\n"
                + json.dumps(
                    {
                        "title": event_generated.title,
                        "content": event.content,
                    },
                    ensure_ascii=False,
                )
                + "\n\n# Original-source evidence returned by `read_source`\n\n"
                + source_read_results
                + "\n\n# Collected reference results\n\n"
                + reference_text
            ),
            error_message="Invalid game design insight artifact",
            validator=lambda generated: self._validate_insight_blocks(
                generated, insight_block.id
            ),
        )
        if insight_generated.decision == "reject":
            raise EnrichmentRejected(insight_generated.rejection_reason)

        insight = insight_generated.insight
        if insight is None:
            raise ValueError("Published editorial decision is missing its insight")
        by_id = {event.id: event}
        by_id[insight.id] = insight
        if systems_block is not None:
            systems_generated = await self._complete_model(
                GeneratedSystemsQuestion,
                system=systems_question_prompt(profile, language, systems_block),
                user=(
                    item_context(
                        item,
                        profile,
                        include_content=True,
                        include_research=False,
                    )
                    + "\n\n# Event narration from the first editor\n\n"
                    + json.dumps(
                        {
                            "title": event_generated.title,
                            "content": event.content,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n# Core discovery from the second editor\n\n"
                    + json.dumps(
                        {
                            "title": insight.title,
                            "content": insight.content,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n# Collected reference results\n\n"
                    + reference_text
                ),
                error_message="Invalid systems question artifact",
                validator=lambda generated: self._validate_systems_question(
                    generated, systems_block.id
                ),
            )
            by_id[systems_generated.question.id] = systems_generated.question
        blocks = [
            by_id[block.id]
            for block in configured_blocks
            if block.id in by_id
        ]
        for block in blocks:
            block.primary = configured_by_id[block.id].primary
        return GeneratedArtifact(title=event_generated.title, blocks=blocks)

    @staticmethod
    def _read_source(
        item: ContentItem,
        profile: LoadedProfile,
        requests: list[SourceReadRequest],
    ) -> str:
        """Execute bounded reads against the original body, excluding comments."""
        source = split_content(item.content).main
        if not source:
            return "The `read_source` tool found no original source body."

        remaining = min(profile.definition.content.enrichment_max_chars, 8000)
        rendered: list[str] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for index, request in enumerate(requests, start=1):
            arguments = request.arguments
            terms = tuple(term.strip() for term in arguments.terms if term.strip())
            key = (arguments.mode, terms)
            if key in seen or remaining <= 0:
                continue
            seen.add(key)

            read_limit = min(
                5000 if arguments.mode == "sample" else 2500,
                remaining,
            )
            if arguments.mode == "sample":
                excerpt = select_content(
                    source,
                    read_limit,
                    profile.definition.content.sampling,
                )
            else:
                excerpt = select_matching_content(source, list(terms), read_limit)

            result_id = f"read-source-{index}"
            if excerpt:
                rendered.append(
                    f"<read_source_result id=\"{result_id}\" mode=\"{arguments.mode}\">\n"
                    f"Purpose: {request.purpose}\n"
                    f"{excerpt}\n"
                    "</read_source_result>"
                )
                remaining -= len(excerpt)
            else:
                rendered.append(
                    f"<read_source_result id=\"{result_id}\" mode=\"{arguments.mode}\">\n"
                    f"Purpose: {request.purpose}\n"
                    "No matching source text was found.\n"
                    "</read_source_result>"
                )

        return "\n\n".join(rendered) or "The `read_source` tool returned no results."

    @staticmethod
    def _validate_event_block(
        generated: GeneratedBlockWithHeader, expected_id: str
    ) -> None:
        if generated.block is None:
            raise ValueError(f"missing required block: {expected_id}")
        if generated.block.id != expected_id:
            raise ValueError(
                f"block ID {generated.block.id} does not match {expected_id}"
            )

    @staticmethod
    def _validate_insight_blocks(
        generated: GeneratedInsight, expected_id: str
    ) -> None:
        if generated.decision == "publish" and generated.insight:
            if generated.insight.id != expected_id:
                raise ValueError(
                    f"insight block ID {generated.insight.id} does not match {expected_id}"
                )

    @staticmethod
    def _validate_systems_question(
        generated: GeneratedSystemsQuestion, expected_id: str
    ) -> None:
        if generated.question.id != expected_id:
            raise ValueError(
                f"systems question block ID {generated.question.id} does not match {expected_id}"
            )

    @staticmethod
    def _sources_from_tool_results(
        results: list[ToolResult],
    ) -> dict[str, ArtifactSource]:
        sources = {}
        for result in results:
            for index, entry in enumerate(result.results, start=1):
                source_id = f"{result.request_id}-{index}"
                sources[source_id] = ArtifactSource(
                    id=source_id,
                    title=entry["title"],
                    url=entry["url"],
                )
        return sources

    @staticmethod
    def _validate_blocks(
        blocks: list[ContentBlock],
        profile: LoadedProfile,
        tool_results: list[ToolResult],
    ) -> None:
        configured: dict[str, ProfileBlock] = {
            block.id: block for block in profile.definition.enrichment.blocks
        }
        seen = set()
        for block in blocks:
            if block.id not in configured:
                raise ValueError(f"Artifact contains unknown block: {block.id}")
            if block.id in seen:
                raise ValueError(f"Artifact contains duplicate block: {block.id}")
            seen.add(block.id)
            if not block.title.strip() or not block.content.strip():
                raise ValueError(f"Artifact block {block.id} cannot be empty")
            result_scope = (
                tool_results
                if profile.editorial_prompt
                else [result for result in tool_results if result.block_id == block.id]
            )
            block_source_ids = {
                f"{result.request_id}-{index}"
                for result in result_scope
                for index, _ in enumerate(result.results, start=1)
            }
            unknown_refs = set(block.source_refs) - block_source_ids
            if unknown_refs:
                raise ValueError(
                    f"Block {block.id} contains unknown source refs: "
                    f"{', '.join(sorted(unknown_refs))}"
                )
        required = {block.id for block in configured.values() if not block.optional}
        missing = required - seen
        if missing:
            raise ValueError(
                f"Artifact is missing required blocks: {', '.join(sorted(missing))}"
            )
