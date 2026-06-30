"""Scrape Reddit's public Atom/RSS feeds for ticker mentions.

!! COMPLIANCE NOTE — read before enabling !!
Reddit's robots.txt (https://www.reddit.com/robots.txt) is ``Disallow: /`` for
all paths, including these RSS feeds, and points to Reddit's Public Content
Policy for the sanctioned ways to access content programmatically (the
official Data API, or the research-access process). The feeds *do* respond
(no auth wall), but using them for sustained automated polling is outside
Reddit's stated policy, not merely an unauthenticated-but-fine gray area.

This module exists because the official OAuth path was unavailable and
ApeWisdom (see ``apewisdom_client.py``) doesn't track the smaller subreddits
this scanner needs. Using it is a deliberate, informed tradeoff: it works
technically, but carries real risk (IP/UA blocks, ToS exposure) for sustained
or commercial-leaning automated use. Prefer official OAuth access
(``reddit_client.py``) wherever possible; treat this as a stopgap, not the
permanent design.

We throttle aggressively (default 2s between requests, single retry with
backoff on 429) to be as unobtrusive as the unauthenticated rate limit allows.
"""

from __future__ import annotations

import html as html_module
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set

import requests

from .config import Config
from .models import RedditSignal
from .reddit_aggregate import aggregate_from_posts

log = logging.getLogger(__name__)

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_TAG_RE = re.compile(r"<[^>]+>")
PROVIDER = "reddit_rss"


def _strip_html(raw: str) -> str:
    # Reddit's <content type="html"> is HTML-escaped (entities like &lt;div&gt;
    # rather than literal tags), so unescape first or the tag regex never matches.
    unescaped = html_module.unescape(raw or "")
    return _TAG_RE.sub(" ", unescaped)


class RedditRSSClient:
    def __init__(self, config: Config, session: Optional[requests.Session] = None):
        self.cfg = config
        self.session = session or requests.Session()
        self._warned = False

    def _warn_once(self) -> None:
        if not self._warned:
            log.warning(
                "Using Reddit's public RSS feeds for r/%s — this conflicts with "
                "Reddit's robots.txt (Disallow: /). Throttled and best-effort; "
                "switch to REDDIT_MODE=praw with real OAuth credentials when "
                "available. See reddit_rss_client.py for details.",
                ",".join(self.cfg.reddit_rss_subreddits),
            )
            self._warned = True

    def _fetch_listing(self, subreddit: str, kind: str) -> List[dict]:
        url = f"https://www.reddit.com/r/{subreddit}/{kind}/.rss"
        params = {"limit": 100}
        headers = {"User-Agent": self.cfg.reddit_user_agent}
        max_attempts = 3
        for attempt in range(max_attempts):
            resp = self.session.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 429 and attempt < max_attempts - 1:
                backoff = self.cfg.reddit_rss_delay_seconds * (3 ** (attempt + 1))
                log.warning(
                    "rate limited on r/%s/%s, backing off %.0fs (attempt %d/%d)",
                    subreddit, kind, backoff, attempt + 1, max_attempts,
                )
                time.sleep(backoff)
                continue
            if resp.status_code != 200:
                log.warning(
                    "r/%s/%s returned %d, skipping", subreddit, kind, resp.status_code
                )
                return []
            break
        else:
            return []

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            log.warning("failed to parse RSS for r/%s/%s: %s", subreddit, kind, exc)
            return []

        posts = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            title_el = entry.find("atom:title", _ATOM_NS)
            content_el = entry.find("atom:content", _ATOM_NS)
            author_el = entry.find("atom:author/atom:name", _ATOM_NS)
            published_el = entry.find("atom:published", _ATOM_NS)

            title = (title_el.text or "") if title_el is not None else ""
            content = _strip_html(content_el.text or "") if content_el is not None else ""
            author = (author_el.text or "").lstrip("/u").lstrip("/") if author_el is not None else ""
            created_utc = 0.0
            if published_el is not None and published_el.text:
                try:
                    created_utc = time.mktime(
                        time.strptime(published_el.text[:19], "%Y-%m-%dT%H:%M:%S")
                    )
                except ValueError:
                    pass

            posts.append(
                {
                    "title": title,
                    "selftext": content,
                    "author": author or "[deleted]",
                    "score": 0,  # not exposed by the unauthenticated feed
                    "created_utc": created_utc,
                    "subreddit": subreddit,
                }
            )
        return posts

    def scan(self, known_symbols: Optional[Set[str]] = None) -> Dict[str, RedditSignal]:
        self._warn_once()
        all_posts: List[dict] = []
        seen_ids: Set[str] = set()
        subs = self.cfg.reddit_rss_subreddits
        for i, sub in enumerate(subs):
            for kind in ("new", "hot"):
                posts = self._fetch_listing(sub, kind)
                for p in posts:
                    key = (sub, p["title"], p["author"])
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    all_posts.append(p)
                time.sleep(self.cfg.reddit_rss_delay_seconds)
        log.info("RSS scan collected %d unique posts across %d subreddits", len(all_posts), len(subs))
        return aggregate_from_posts(
            all_posts, known_symbols, self.cfg.reddit_lookback_hours, PROVIDER
        )
