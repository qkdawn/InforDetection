"""Select bounded source content for profile-driven AI stages."""

from dataclasses import dataclass
import re
from typing import Literal


COMMENTS_MARKER = "--- Top Comments ---"


@dataclass(frozen=True)
class ContentParts:
    main: str
    comments: str


def split_content(content: str | None) -> ContentParts:
    """Separate source content from appended community comments."""
    if not content:
        return ContentParts(main="", comments="")
    if COMMENTS_MARKER not in content:
        return ContentParts(main=content.strip(), comments="")
    main, comments = content.split(COMMENTS_MARKER, 1)
    return ContentParts(main=main.strip(), comments=comments.strip())


def select_content(
    content: str,
    max_chars: int,
    sampling: Literal["prefix", "head-middle-tail"],
) -> str:
    """Return a bounded excerpt while preserving a long article's conclusion."""
    text = content.strip()
    if len(text) <= max_chars:
        return text
    if sampling == "prefix":
        return text[:max_chars].rstrip()

    markers = (
        "[Opening excerpt]\n",
        "\n\n[Middle excerpt]\n",
        "\n\n[Closing excerpt]\n",
    )
    available = max_chars - sum(len(marker) for marker in markers)
    opening_size = int(available * 0.4)
    middle_size = int(available * 0.3)
    closing_size = available - opening_size - middle_size
    midpoint = len(text) // 2
    middle_start = max(0, midpoint - middle_size // 2)

    opening = text[:opening_size].rstrip()
    middle = text[middle_start : middle_start + middle_size].strip()
    closing = text[-closing_size:].lstrip()
    return (
        markers[0]
        + opening
        + markers[1]
        + middle
        + markers[2]
        + closing
    )


def select_matching_content(
    content: str,
    terms: list[str],
    max_chars: int,
    *,
    context_chars: int = 500,
) -> str:
    """Return bounded source windows around exact terms, in document order."""
    text = content.strip()
    normalized_terms = list(
        dict.fromkeys(term.strip().casefold() for term in terms if term.strip())
    )
    if not text or not normalized_terms or max_chars <= 0:
        return ""

    lowered = text.casefold()
    matches: list[tuple[int, int]] = []
    for term in normalized_terms:
        start = 0
        while len(matches) < 12:
            index = lowered.find(term, start)
            if index < 0:
                break
            matches.append((index, index + len(term)))
            start = index + max(len(term), 1)

    if not matches:
        return ""

    longest_term = max(len(term) for term in normalized_terms)
    effective_context = min(
        context_chars,
        max(0, (max_chars - longest_term - 40) // 2),
    )
    windows = sorted(
        (
            max(0, start - effective_context),
            min(len(text), end + effective_context),
        )
        for start, end in matches
    )
    merged: list[list[int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    excerpts: list[str] = []
    remaining = max_chars
    for index, (start, end) in enumerate(merged, start=1):
        marker = f"[Matching excerpt {index}]\n"
        if remaining <= len(marker):
            break
        excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
        excerpt = excerpt[: remaining - len(marker)].rstrip()
        if not excerpt:
            continue
        excerpts.append(marker + excerpt)
        remaining -= len(marker) + len(excerpt) + 2
        if remaining <= 0:
            break
    return "\n\n".join(excerpts)
