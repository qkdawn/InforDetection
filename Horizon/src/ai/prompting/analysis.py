"""Prompt construction for profile-driven content analysis."""

from ...models import ContentItem
from ...processing.profiles import LoadedProfile
from .common import EVIDENCE_RULES, UNTRUSTED_INPUT_RULE

ANALYSIS_RULES = f"""You are a content curator evaluating an item under the supplied processing profile.

- {UNTRUSTED_INPUT_RULE}
- Base the analysis only on the supplied item and its metadata.
{EVIDENCE_RULES}
- Apply the profile's evaluation policy consistently."""


def analysis_system_prompt(profile: LoadedProfile) -> str:
    editorial_context = (
        f"\n\n# Editorial stance\n\n{profile.editorial_prompt}"
        if profile.editorial_prompt
        else ""
    )
    return f"""{ANALYSIS_RULES}{editorial_context}

# Profile policy

{profile.analysis_prompt}

# Output contract

Return valid JSON only:
{{
  "score": <number from 0 to 10, or null when this profile does not score>,
  "reason": "<concise explanation>",
  "summary": "<one-sentence summary>",
  "tags": ["<tag>", "..."]
}}"""


def analysis_user_prompt(
    item: ContentItem,
    content_section: str,
    discussion_section: str,
) -> str:
    return f"""Analyze the following content.

Title: {item.title}
Source: {item.source_type.value}
Author: {item.author or "Unknown"}
URL: {item.url}
{content_section}
{discussion_section}"""
