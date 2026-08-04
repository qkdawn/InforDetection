from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
import httpx
import pytest

from src.models import RSSSourceConfig
from src.scrapers.rss import RSSFeedResult, RSSScraper

_FEED = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel><title>Test</title>
  <item>
    <guid>entry-1</guid>
    <title>Item 1</title>
    <link>https://example.com/item-1</link>
    <pubDate>Fri, 24 Apr 2026 12:00:00 GMT</pubDate>
    <description>Short summary from feed.</description>
  </item>
</channel></rss>
"""
_SINCE = datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc)


def _make_feed_client(feed_text: str) -> AsyncMock:
    response = MagicMock()
    response.text = feed_text
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    return client


def test_rss_ids_are_deterministic() -> None:
    client = _make_feed_client(_FEED)
    source = RSSSourceConfig(
        name="Test", url="https://example.com/feed.xml", profile="rss-profile"
    )
    scraper = RSSScraper([source], client)

    first_item = asyncio.run(scraper.fetch(_SINCE))[0]
    first = first_item.id
    second = asyncio.run(scraper.fetch(_SINCE))[0].id

    assert first == second
    assert first == "rss:example.com_feed.xml:5e2d5d1e58e94d76"
    assert first_item.profile == "rss-profile"


def _make_registry(name: str, extractor):
    registry = MagicMock()
    registry.get.side_effect = lambda n: extractor if n == name else None
    return registry


def test_content_extractor_replaces_feed_content() -> None:
    client = _make_feed_client(_FEED)
    extractor = AsyncMock()
    extractor.extract.return_value = "Full article text from extractor."

    source = RSSSourceConfig(
        name="Test", url="https://example.com/feed.xml", content_extractor="my-ext"
    )
    scraper = RSSScraper([source], client, extractors=_make_registry("my-ext", extractor))
    items = asyncio.run(scraper.fetch(_SINCE))

    assert len(items) == 1
    assert items[0].content == "Full article text from extractor."
    extractor.extract.assert_awaited_once_with("https://example.com/item-1", client)


def test_content_extractor_falls_back_on_none() -> None:
    client = _make_feed_client(_FEED)
    extractor = AsyncMock()
    extractor.extract.return_value = None  # extraction failed

    source = RSSSourceConfig(
        name="Test", url="https://example.com/feed.xml", content_extractor="my-ext"
    )
    scraper = RSSScraper([source], client, extractors=_make_registry("my-ext", extractor))
    items = asyncio.run(scraper.fetch(_SINCE))

    assert len(items) == 1
    assert items[0].content == "Short summary from feed."


def test_unknown_extractor_name_ignored() -> None:
    client = _make_feed_client(_FEED)
    source = RSSSourceConfig(
        name="Test", url="https://example.com/feed.xml", content_extractor="nonexistent"
    )
    scraper = RSSScraper([source], client, extractors=_make_registry("other", AsyncMock()))
    items = asyncio.run(scraper.fetch(_SINCE))

    assert len(items) == 1
    assert items[0].content == "Short summary from feed."


def test_empty_feed_is_reported_as_empty_not_failure() -> None:
    client = _make_feed_client(
        '<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
    )
    source = RSSSourceConfig(
        name="No posts", url="https://example.com/empty.xml", profile="rss-profile"
    )
    scraper = RSSScraper([source], client)

    assert asyncio.run(scraper.fetch(_SINCE)) == []
    assert scraper.last_source_outcomes[0].status == "empty"
    assert scraper.last_source_outcomes[0].error is None


def test_http_error_is_reported_as_failure() -> None:
    response = MagicMock(status_code=503)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "service unavailable", request=MagicMock(), response=response
    )
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Unavailable", url="https://example.com/down.xml", profile="rss-profile"
    )
    scraper = RSSScraper([source], client)

    assert asyncio.run(scraper.fetch(_SINCE)) == []
    result = scraper.last_source_outcomes[0]
    assert result.status == "failure"
    assert result.error == "HTTP 503"


def test_transient_http_error_is_retried(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSS_RETRY_BACKOFF", "0")
    failing = MagicMock(status_code=503)
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "service unavailable", request=MagicMock(), response=failing
    )
    healthy = MagicMock(text=_FEED, content=_FEED.encode())
    healthy.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.side_effect = [failing, healthy]
    source = RSSSourceConfig(
        name="Flaky", url="https://example.com/flaky.xml", profile="rss-profile"
    )

    items = asyncio.run(RSSScraper([source], client).fetch(_SINCE))

    assert len(items) == 1
    assert client.get.await_count == 2
    assert client.get.await_args_list[0].kwargs["headers"]["User-Agent"].startswith(
        "Horizon/"
    )


def test_permanent_rsshub_account_error_is_not_retried(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSS_RETRY_BACKOFF", "0")
    response = MagicMock(
        status_code=503,
        text="Error Message: This account doesn't exist",
    )
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "account does not exist", request=MagicMock(), response=response
    )
    client = AsyncMock()
    client.get.return_value = response

    scraper = RSSScraper([], client)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            scraper._request_with_retries(
                "http://rsshub:1200/twitter/user/removed/exclude_rts_replies"
            )
        )

    assert client.get.await_count == 1


def test_reddit_feeds_are_serialized(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_REDDIT_CONCURRENCY", "1")
    monkeypatch.setenv("HORIZON_REDDIT_MIN_INTERVAL_SECONDS", "0")
    client = AsyncMock()
    sources = [
        RSSSourceConfig(
            name="Reddit one",
            url="http://rsshub:1200/reddit/subreddit/gamedesign",
        ),
        RSSSourceConfig(
            name="Reddit two",
            url="http://rsshub:1200/reddit/subreddit/truegaming",
        ),
    ]
    scraper = RSSScraper(sources, client)
    active = 0
    peak = 0

    async def fake_fetch(source, since):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return RSSFeedResult(source=source, status="empty")

    monkeypatch.setattr(scraper, "_fetch_feed", fake_fetch)

    assert asyncio.run(scraper.fetch(_SINCE)) == []
    assert peak == 1


def test_reddit_429_honors_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSS_RETRY_BACKOFF", "0")
    monkeypatch.setenv("HORIZON_REDDIT_RETRIES", "1")
    monkeypatch.setenv("HORIZON_REDDIT_RETRY_BACKOFF_SECONDS", "5")
    failing = MagicMock(status_code=429, headers={"Retry-After": "7"})
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited", request=MagicMock(), response=failing
    )
    healthy = MagicMock(text=_FEED, content=_FEED.encode())
    healthy.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.side_effect = [failing, healthy]
    sleep = AsyncMock()
    monkeypatch.setattr("src.scrapers.rss.asyncio.sleep", sleep)
    scraper = RSSScraper([], client)

    response = asyncio.run(
        scraper._request_with_retries("https://www.reddit.com/r/gamedesign/.rss")
    )

    assert response is healthy
    sleep.assert_awaited_once_with(7.0)


def test_rsshub_reddit_route_falls_back_to_native_rss(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSS_RETRY_BACKOFF", "0")
    failing = MagicMock(status_code=404)
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found", request=MagicMock(), response=failing
    )
    healthy = MagicMock(text=_FEED, content=_FEED.encode())
    healthy.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.side_effect = [failing, healthy]
    source = RSSSourceConfig(
        name="Reddit", url="https://rss.example/reddit/subreddit/gamedesign"
    )

    items = asyncio.run(RSSScraper([source], client).fetch(_SINCE))

    assert len(items) == 1
    assert str(client.get.await_args_list[1].args[0]) == (
        "https://www.reddit.com/r/gamedesign/.rss"
    )


def test_reddit_route_prefers_oauth_and_reuses_token(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "windows:test:v1.0 (by /u/tester)")
    token_response = MagicMock()
    token_response.json.return_value = {
        "access_token": "access-token",
        "expires_in": 3600,
    }
    token_response.raise_for_status.return_value = None
    listing_response = MagicMock()
    listing_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "name": "t3_post1",
                        "title": "OAuth Reddit post",
                        "permalink": "/r/gamedesign/comments/post1/test/",
                        "author": "designer",
                        "selftext": "Post body",
                        "created_utc": 1777032000,
                    }
                }
            ]
        }
    }
    listing_response.raise_for_status.return_value = None
    client = AsyncMock()
    client.post.return_value = token_response
    client.get.return_value = listing_response
    sources = [
        RSSSourceConfig(
            name="Reddit one",
            url="http://rsshub:1200/reddit/subreddit/gamedesign",
        ),
        RSSSourceConfig(
            name="Reddit two",
            url="http://rsshub:1200/reddit/subreddit/truegaming",
        ),
    ]

    items = asyncio.run(RSSScraper(sources, client).fetch(_SINCE))

    assert [item.title for item in items] == [
        "OAuth Reddit post",
        "OAuth Reddit post",
    ]
    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["auth"] == ("client-id", "client-secret")
    assert all(
        call.args[0].startswith("https://oauth.reddit.com/r/")
        for call in client.get.await_args_list
    )
    assert all(
        call.kwargs["headers"]["Authorization"] == "Bearer access-token"
        for call in client.get.await_args_list
    )


def test_moved_feed_is_discovered_from_parent_page(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSS_RETRY_BACKOFF", "0")
    missing = MagicMock(status_code=404)
    missing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not found", request=MagicMock(), response=missing
    )
    landing_html = (
        '<html><head><link rel="alternate" type="application/rss+xml" '
        'href="/new-feed.xml"></head></html>'
    )
    landing = MagicMock(text=landing_html, content=landing_html.encode())
    landing.raise_for_status.return_value = None
    healthy = MagicMock(text=_FEED, content=_FEED.encode())
    healthy.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.side_effect = [missing, landing, healthy]
    source = RSSSourceConfig(
        name="Moved", url="https://example.com/blog/old-feed.xml"
    )

    items = asyncio.run(RSSScraper([source], client).fetch(_SINCE))

    assert len(items) == 1
    requested = [str(call.args[0]) for call in client.get.await_args_list]
    assert requested == [
        "https://example.com/blog/old-feed.xml",
        "https://example.com/blog/",
        "https://example.com/new-feed.xml",
    ]


def test_date_without_timezone_is_normalized_to_utc() -> None:
    scraper = RSSScraper([], AsyncMock())

    parsed = scraper._parse_date({"published": "Fri, 24 Apr 2026 12:00:00"})

    assert parsed is not None
    assert parsed.tzinfo == timezone.utc


def test_rsshub_twitter_requests_are_serialized(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_RSSHUB_TWITTER_CONCURRENCY", "1")

    class TrackingClient:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.timeouts = []

        async def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.timeouts.append(kwargs["timeout"])
            await asyncio.sleep(0.01)
            self.active -= 1
            response = MagicMock(text=_FEED, content=_FEED.encode())
            response.raise_for_status.return_value = None
            return response

    client = TrackingClient()
    sources = [
        RSSSourceConfig(
            name="X one", url="http://rsshub:1200/twitter/user/one"
        ),
        RSSSourceConfig(
            name="X two", url="http://rsshub:1200/twitter/user/two"
        ),
    ]

    items = asyncio.run(RSSScraper(sources, client).fetch(_SINCE))  # type: ignore[arg-type]

    assert len(items) == 2
    assert client.max_active == 1
    assert all(timeout.read == 90.0 for timeout in client.timeouts)
