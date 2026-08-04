"""RSS feed scraper implementation."""

import asyncio
import calendar
import hashlib
import logging
import os
import re
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Literal, Optional
from email.utils import format_datetime, parsedate_to_datetime
from xml.etree import ElementTree
import httpx
import feedparser

from .base import BaseScraper
from ..extractors import ExtractorRegistry
from ..models import ContentItem, SourceType, RSSSourceConfig

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_DEFAULT_USER_AGENT = "Horizon/0.1 (+https://github.com/openai/horizon)"


@dataclass
class RSSFeedResult:
    """Per-feed fetch result used for diagnostics."""

    source: RSSSourceConfig
    status: Literal["success", "empty", "failure"]
    items: List[ContentItem] = field(default_factory=list)
    error: Optional[str] = None


class RSSScraper(BaseScraper):
    """Scraper for RSS/Atom feeds."""

    def __init__(
        self,
        sources: List[RSSSourceConfig],
        http_client: httpx.AsyncClient,
        extractors: Optional[ExtractorRegistry] = None,
    ):
        """Initialize RSS scraper.

        Args:
            sources: List of RSS feed configurations
            http_client: Shared async HTTP client
            extractors: Optional registry of content extractors for full article fetching
        """
        super().__init__({"sources": sources}, http_client)
        self._extractors = extractors
        self.last_source_outcomes: List[RSSFeedResult] = []
        self._reddit_token: tuple[str, float] | None = None
        self._reddit_token_lock = asyncio.Lock()
        self._reddit_request_lock = asyncio.Lock()
        self._reddit_last_request_at = 0.0

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch RSS feed items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        sources = [source for source in self.config["sources"] if source.enabled]
        try:
            configured_concurrency = int(os.getenv("HORIZON_RSS_CONCURRENCY", "8"))
        except ValueError:
            configured_concurrency = 8
        concurrency = max(1, min(configured_concurrency, 32))
        semaphore = asyncio.Semaphore(concurrency)
        try:
            twitter_concurrency = int(
                os.getenv("HORIZON_RSSHUB_TWITTER_CONCURRENCY", "1")
            )
        except ValueError:
            twitter_concurrency = 1
        twitter_semaphore = asyncio.Semaphore(
            max(1, min(twitter_concurrency, concurrency))
        )
        try:
            reddit_concurrency = int(os.getenv("HORIZON_REDDIT_CONCURRENCY", "1"))
        except ValueError:
            reddit_concurrency = 1
        reddit_semaphore = asyncio.Semaphore(
            max(1, min(reddit_concurrency, concurrency))
        )

        async def fetch_one(source: RSSSourceConfig) -> RSSFeedResult:
            async with semaphore:
                if self._is_twitter_route(str(source.url)):
                    async with twitter_semaphore:
                        return await self._fetch_feed(source, since)
                if self._is_reddit_route(str(source.url)):
                    async with reddit_semaphore:
                        await self._wait_for_reddit_slot()
                        return await self._fetch_feed(source, since)
                return await self._fetch_feed(source, since)

        results = await asyncio.gather(*(fetch_one(source) for source in sources))
        self.last_source_outcomes = list(results)
        return [item for result in results for item in result.items]

    async def _fetch_feed(
        self, source: RSSSourceConfig, since: datetime
    ) -> RSSFeedResult:
        """Fetch items from a single RSS feed.

        Args:
            source: RSS feed configuration
            since: Only fetch items after this time

        Returns:
            RSSFeedResult: Items and per-feed status
        """
        items = []

        try:
            # Expand environment variables in URL (e.g. ${LWN_TOKEN})
            feed_url = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)).strip(),
                str(source.url),
            )

            # Fetch feed content. A number of public feeds are slow or reject
            # the default httpx user agent, so use a descriptive client header
            # and retry only errors that are likely to be transient.
            response, resolved_url = await self._get_feed_response(feed_url)

            # Parse feed
            response_body = getattr(response, "content", None)
            if not isinstance(response_body, (bytes, bytearray)):
                response_body = response.text
            feed = feedparser.parse(response_body)

            # A valid feed with no entries is a normal empty result. A response
            # that cannot be parsed is a source failure, not a no-post day.
            if not feed.entries and getattr(feed, "bozo", False):
                # Some sites publish an HTML landing page at the configured
                # URL but advertise the real feed in a link tag. Follow that
                # hint once before reporting a parse failure.
                discovered = self._discover_feed_urls(
                    response.text, resolved_url
                )
                for candidate in discovered:
                    try:
                        alternate_response, alternate_url = await self._get_feed_response(
                            candidate, allow_fallback=False
                        )
                    except (httpx.HTTPError, httpx.TimeoutException):
                        continue
                    alternate_body = getattr(alternate_response, "content", None)
                    if not isinstance(alternate_body, (bytes, bytearray)):
                        alternate_body = alternate_response.text
                    alternate_feed = feedparser.parse(alternate_body)
                    if alternate_feed.entries or not getattr(alternate_feed, "bozo", False):
                        feed = alternate_feed
                        resolved_url = alternate_url
                        break
                if not feed.entries and getattr(feed, "bozo", False):
                    parse_error = getattr(feed, "bozo_exception", None)
                    return RSSFeedResult(
                        source=source,
                        status="failure",
                        error=f"FeedParseError: {parse_error or 'invalid feed'}",
                    )

            for entry in feed.entries:
                # Parse published date
                published_at = self._parse_date(entry)
                if not published_at or published_at < since:
                    continue

                # Generate unique ID from feed URL and entry ID
                feed_id = str(source.url).split("//")[1].replace("/", "_")
                entry_id = entry.get("id", entry.get("link", ""))
                entry_hash = hashlib.sha256(str(entry_id).encode("utf-8")).hexdigest()[
                    :16
                ]

                # Extract content
                content = self._extract_content(entry)

                if source.content_extractor and self._extractors:
                    extractor = self._extractors.get(source.content_extractor)
                    if extractor:
                        url = entry.get("link", "")
                        if url:
                            try:
                                full = await extractor.extract(url, self.client)
                            except Exception as exc:
                                logger.info(
                                    "Content extraction failed for %s (%s): %s",
                                    source.name,
                                    url,
                                    exc,
                                )
                            else:
                                if full:
                                    content = full

                item = ContentItem(
                    id=self._generate_id("rss", feed_id, entry_hash),
                    source_type=SourceType.RSS,
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", str(source.url)),
                    content=content,
                    author=entry.get("author", source.name),
                    published_at=published_at,
                    profile=source.profile,
                    metadata={
                        "feed_name": source.name,
                        "category": source.category,
                        "tags": [tag.term for tag in entry.get("tags", [])],
                    },
                )
                items.append(item)

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response is not None else "?"
            error = f"HTTP {status_code}"
            logger.warning("Error fetching RSS feed %s: %s", source.name, error)
            return RSSFeedResult(source=source, status="failure", error=error)
        except httpx.TimeoutException as e:
            error = "Timeout: request timed out"
            logger.warning("Error fetching RSS feed %s: %s", source.name, error)
            return RSSFeedResult(source=source, status="failure", error=error)
        except httpx.HTTPError as e:
            error = f"HTTPError: {e}"
            logger.warning("Error fetching RSS feed %s: %s", source.name, error)
            return RSSFeedResult(source=source, status="failure", error=error)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.warning("Error parsing RSS feed %s: %s", source.name, error)
            return RSSFeedResult(source=source, status="failure", error=error)

        return RSSFeedResult(source=source, status="success" if items else "empty", items=items)

    async def _get_feed_response(
        self, feed_url: str, *, allow_fallback: bool = True
    ) -> tuple[httpx.Response, str]:
        """Fetch a feed, retrying transient failures and known route aliases."""
        if allow_fallback and self._reddit_credentials() and self._reddit_subreddit(feed_url):
            try:
                oauth_response = await self._request_reddit_oauth_feed(feed_url)
                return oauth_response, feed_url
            except httpx.HTTPError as exc:
                logger.warning("Reddit OAuth fetch failed; trying RSS fallback: %s", exc)
        candidates = [feed_url]
        if allow_fallback:
            candidates.extend(self._fallback_urls(feed_url))
        last_error: httpx.HTTPError | None = None
        for candidate in candidates:
            try:
                response = await self._request_with_retries(candidate)
                response_url = getattr(response, "url", None)
                resolved_url = (
                    str(response_url)
                    if isinstance(response_url, (str, httpx.URL))
                    else candidate
                )
                return response, resolved_url
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else None
                # A fallback is useful for an obsolete RSSHub route, but not
                # for a normal source that simply returns a 404.
                if status not in {400, 403, 404, 406, 410, 500, 502, 503, 504}:
                    break
            except httpx.HTTPError as exc:
                last_error = exc
                break
        if (
            allow_fallback
            and isinstance(last_error, httpx.HTTPStatusError)
            and last_error.response is not None
            and last_error.response.status_code in {404, 410}
            and not self._fallback_urls(feed_url)
        ):
            discovered_response = await self._discover_from_website(feed_url)
            if discovered_response is not None:
                return discovered_response
        if last_error is not None:
            raise last_error
        raise httpx.HTTPError(f"Unable to fetch RSS feed: {feed_url}")

    async def _request_with_retries(self, feed_url: str) -> httpx.Response:
        try:
            retry_count = int(os.getenv("HORIZON_RSS_RETRIES", "2"))
        except ValueError:
            retry_count = 2
        retry_count = max(0, min(retry_count, 5))
        reddit_route = self._is_reddit_route(feed_url)
        if reddit_route:
            try:
                reddit_retry_count = int(os.getenv("HORIZON_REDDIT_RETRIES", "1"))
            except ValueError:
                reddit_retry_count = 1
            retry_count = max(0, min(reddit_retry_count, retry_count))
        try:
            backoff = float(os.getenv("HORIZON_RSS_RETRY_BACKOFF", "0.35"))
        except ValueError:
            backoff = 0.35
        backoff = max(0.0, min(backoff, 10.0))
        twitter_route = self._is_twitter_route(feed_url)
        if twitter_route:
            # RSSHub serializes each configured X auth token internally. Give
            # that route time to acquire the token and finish its upstream call.
            retry_count = min(retry_count, 1)
            try:
                read_timeout = float(
                    os.getenv("HORIZON_RSSHUB_TWITTER_TIMEOUT", "90")
                )
            except ValueError:
                read_timeout = 90.0
            read_timeout = max(30.0, min(read_timeout, 180.0))
        else:
            read_timeout = 45.0
        headers = {
            "User-Agent": os.getenv("HORIZON_HTTP_USER_AGENT", _DEFAULT_USER_AGENT),
            "Accept": (
                "application/rss+xml, application/atom+xml, application/xml, "
                "text/xml;q=0.9, text/html;q=0.5, */*;q=0.1"
            ),
        }
        for attempt in range(retry_count + 1):
            retry_after = None
            status = None
            try:
                response = await self.client.get(
                    feed_url,
                    headers=headers,
                    follow_redirects=True,
                    timeout=httpx.Timeout(
                        connect=15.0,
                        read=read_timeout,
                        write=15.0,
                        pool=15.0,
                    ),
                )
                response.raise_for_status()
                return response
            except httpx.TimeoutException:
                if attempt >= retry_count:
                    raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                response_text = ""
                if exc.response is not None:
                    try:
                        response_text = exc.response.text.lower()
                    except (AttributeError, TypeError):
                        response_text = ""
                permanent_rsshub_error = status == 503 and any(
                    marker in response_text
                    for marker in (
                        "this account doesn&#39;t exist",
                        "this account doesn't exist",
                        "user is suspended",
                    )
                )
                if (
                    status not in _RETRYABLE_STATUS_CODES
                    or permanent_rsshub_error
                    or attempt >= retry_count
                ):
                    raise
                if status == 429:
                    retry_after = self._retry_after_seconds(exc.response)
            delay = backoff * (2**attempt)
            if reddit_route and status == 429:
                try:
                    reddit_backoff = float(
                        os.getenv("HORIZON_REDDIT_RETRY_BACKOFF_SECONDS", "5")
                    )
                except ValueError:
                    reddit_backoff = 5.0
                delay = max(delay, reddit_backoff * (2**attempt))
                if retry_after is not None:
                    delay = max(delay, retry_after)
                delay = min(delay, 60.0)
            if delay:
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _is_twitter_route(feed_url: str) -> bool:
        return urlsplit(feed_url).path.lower().startswith("/twitter/")

    @staticmethod
    def _is_reddit_route(feed_url: str) -> bool:
        parsed = urlsplit(feed_url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        return path.startswith("/reddit/subreddit/") or host.endswith("reddit.com")

    async def _wait_for_reddit_slot(self) -> None:
        try:
            interval = float(
                os.getenv("HORIZON_REDDIT_MIN_INTERVAL_SECONDS", "2")
            )
        except ValueError:
            interval = 2.0
        interval = max(0.0, min(interval, 60.0))
        async with self._reddit_request_lock:
            now = time.monotonic()
            delay = self._reddit_last_request_at + interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._reddit_last_request_at = time.monotonic()

    @staticmethod
    def _retry_after_seconds(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _reddit_subreddit(feed_url: str) -> str | None:
        path = urlsplit(feed_url).path.rstrip("/")
        match = re.fullmatch(r"/reddit/subreddit/([^/]+)", path, flags=re.IGNORECASE)
        return unquote(match.group(1)) if match else None

    @staticmethod
    def _reddit_credentials() -> tuple[str, str] | None:
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        return client_id, client_secret

    async def _request_reddit_oauth_feed(self, feed_url: str) -> httpx.Response:
        subreddit = self._reddit_subreddit(feed_url)
        if not subreddit:
            raise httpx.HTTPError("Not a Reddit subreddit route")
        token = await self._get_reddit_access_token()
        user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            "windows:infordetection:v1.0 (by /u/infordetection)",
        )
        response = await self.client.get(
            f"https://oauth.reddit.com/r/{quote(subreddit, safe='')}/new",
            params={"limit": 50, "raw_json": 1},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )
        response.raise_for_status()
        try:
            rows = response.json().get("data", {}).get("children", [])
        except (AttributeError, ValueError) as exc:
            raise httpx.HTTPError("Invalid Reddit OAuth response") from exc
        rss = ElementTree.Element("rss", version="2.0")
        channel = ElementTree.SubElement(rss, "channel")
        ElementTree.SubElement(channel, "title").text = f"r/{subreddit}"
        ElementTree.SubElement(channel, "link").text = (
            f"https://www.reddit.com/r/{subreddit}/"
        )
        for row in rows:
            post = row.get("data", {}) if isinstance(row, dict) else {}
            permalink = str(post.get("permalink") or "")
            if not permalink:
                continue
            item = ElementTree.SubElement(channel, "item")
            ElementTree.SubElement(item, "guid").text = str(
                post.get("name") or permalink
            )
            ElementTree.SubElement(item, "title").text = str(
                post.get("title") or "Untitled"
            )
            ElementTree.SubElement(item, "link").text = (
                "https://www.reddit.com" + permalink
            )
            ElementTree.SubElement(item, "author").text = str(
                post.get("author") or f"r/{subreddit}"
            )
            description = str(post.get("selftext") or post.get("url") or "")
            ElementTree.SubElement(item, "description").text = description
            try:
                created_at = datetime.fromtimestamp(
                    float(post["created_utc"]), tz=timezone.utc
                )
            except (KeyError, TypeError, ValueError, OSError):
                continue
            ElementTree.SubElement(item, "pubDate").text = format_datetime(
                created_at, usegmt=True
            )
        content = ElementTree.tostring(rss, encoding="utf-8", xml_declaration=True)
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            request=httpx.Request("GET", feed_url),
        )

    async def _get_reddit_access_token(self) -> str:
        if self._reddit_token and self._reddit_token[1] > time.monotonic():
            return self._reddit_token[0]
        async with self._reddit_token_lock:
            if self._reddit_token and self._reddit_token[1] > time.monotonic():
                return self._reddit_token[0]
            credentials = self._reddit_credentials()
            if credentials is None:
                raise httpx.HTTPError("Reddit OAuth credentials are not configured")
            user_agent = os.getenv(
                "REDDIT_USER_AGENT",
                "windows:infordetection:v1.0 (by /u/infordetection)",
            )
            response = await self.client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=credentials,
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": user_agent},
                timeout=httpx.Timeout(30.0),
            )
            response.raise_for_status()
            try:
                payload = response.json()
                token = str(payload["access_token"])
                expires_in = int(payload.get("expires_in", 3600))
            except (KeyError, TypeError, ValueError) as exc:
                raise httpx.HTTPError("Invalid Reddit OAuth token response") from exc
            self._reddit_token = (
                token,
                time.monotonic() + max(30, expires_in - 60),
            )
            return token

    async def _discover_from_website(
        self, feed_url: str
    ) -> tuple[httpx.Response, str] | None:
        """Find a replacement feed advertised by the source website."""
        parsed = urlsplit(feed_url)
        parent_path = parsed.path.rsplit("/", 1)[0].rstrip("/") + "/"
        page_urls = [urlunsplit((parsed.scheme, parsed.netloc, parent_path, "", ""))]
        root_url = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        if root_url not in page_urls:
            page_urls.append(root_url)
        for page_url in page_urls:
            try:
                page = await self._request_with_retries(page_url)
            except httpx.HTTPError:
                continue
            page_response_url = getattr(page, "url", None)
            base_url = (
                str(page_response_url)
                if isinstance(page_response_url, (str, httpx.URL))
                else page_url
            )
            for candidate in self._discover_feed_urls(page.text, base_url):
                if candidate == feed_url:
                    continue
                try:
                    response = await self._request_with_retries(candidate)
                except httpx.HTTPError:
                    continue
                response_url = getattr(response, "url", None)
                resolved_url = (
                    str(response_url)
                    if isinstance(response_url, (str, httpx.URL))
                    else candidate
                )
                return response, resolved_url
        return None

    @staticmethod
    def _fallback_urls(feed_url: str) -> list[str]:
        """Return safe aliases for routes commonly moved by RSSHub/site owners."""
        parsed = urlsplit(feed_url)
        path = parsed.path.rstrip("/")
        match = re.fullmatch(r"/reddit/subreddit/([^/]+)", path, flags=re.IGNORECASE)
        if match:
            subreddit = quote(unquote(match.group(1)), safe="")
            query = parsed.query
            return [
                f"https://www.reddit.com/r/{subreddit}/.rss"
                + (f"?{query}" if query else ""),
                f"https://old.reddit.com/r/{subreddit}/.rss"
                + (f"?{query}" if query else ""),
            ]
        return []

    @staticmethod
    def _discover_feed_urls(body: str, base_url: str) -> list[str]:
        """Extract RSS/Atom alternate links from an HTML response."""
        if not body or "<html" not in body.lower():
            return []
        urls: list[str] = []
        link_pattern = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
        for tag in link_pattern.findall(body):
            if not re.search(r"rel\s*=\s*[\"']?[^>]*alternate", tag, re.IGNORECASE):
                continue
            if not re.search(r"type\s*=\s*[\"']?(?:application|text)/(?:rss|atom)\+?xml", tag, re.IGNORECASE):
                continue
            href = re.search(r"href\s*=\s*[\"']([^\"']+)", tag, re.IGNORECASE)
            if not href:
                continue
            candidate = httpx.URL(base_url).join(href.group(1))
            if str(candidate) not in urls:
                urls.append(str(candidate))
        return urls[:3]

    def _parse_date(self, entry: dict) -> datetime:
        """Parse publication date from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            datetime: Parsed publication date or None
        """
        # Try different date fields
        for field in ["published", "updated", "created"]:
            if field in entry:
                try:
                    # Try parsing structured time first
                    if f"{field}_parsed" in entry and entry[f"{field}_parsed"]:
                        return datetime.fromtimestamp(
                            calendar.timegm(entry[f"{field}_parsed"]), tz=timezone.utc
                        )
                    # Fallback to string parsing
                    date_str = str(entry[field]).strip()
                    parsed = parsedate_to_datetime(date_str)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(timezone.utc)
                except Exception:
                    continue

        return None

    def _extract_content(self, entry: dict) -> str:
        """Extract text content from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            str: Extracted text content
        """
        # Try different content fields
        if "summary" in entry:
            return entry.summary
        if "description" in entry:
            return entry.description
        if "content" in entry and entry.content:
            # content is usually a list
            return entry.content[0].get("value", "")

        return ""
