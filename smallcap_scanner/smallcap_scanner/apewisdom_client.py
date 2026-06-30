"""Client for ApeWisdom (https://apewisdom.io/api/) — a free, no-auth API that
already aggregates Reddit ticker mentions/upvotes per subreddit.

This is the preferred Reddit-adjacent data source where it has coverage: it's
a licensed third party doing the scanning, not us, and it requires no
credentials. Its coverage is limited to the ~30 subreddits it tracks (notably
``wallstreetbets`` and ``pennystocks``) — it does not cover smaller subs like
TheRaceTo10Million, raceto10000, or smallstreetbets. Use
``reddit_rss_client.py`` for those.

ApeWisdom only exposes ticker-level mention/upvote totals, not individual
posts — so there's no author breakdown, and ``RedditSignal.author_diversity``
stays neutral (unknown) for tickers sourced purely from here.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

import requests

from .config import Config
from .models import RedditSignal

log = logging.getLogger(__name__)

PROVIDER = "apewisdom"
_BASE_URL = "https://apewisdom.io/api/v1.0"


class ApeWisdomClient:
    def __init__(self, config: Config, session: Optional[requests.Session] = None):
        self.cfg = config
        self.session = session or requests.Session()

    def _fetch_filter(self, filter_name: str) -> List[dict]:
        results: List[dict] = []
        page = 1
        while True:
            resp = self.session.get(
                f"{_BASE_URL}/filter/{filter_name}/page/{page}", timeout=20
            )
            if resp.status_code != 200:
                log.warning(
                    "ApeWisdom filter=%s page=%d returned %d",
                    filter_name, page, resp.status_code,
                )
                break
            data = resp.json()
            page_results = data.get("results", [])
            results.extend(page_results)
            pages = data.get("pages", 1)
            if page >= pages or not page_results:
                break
            page += 1
            time.sleep(0.3)
        return results

    def scan(self, known_symbols: Optional[Set[str]] = None) -> Dict[str, RedditSignal]:
        """Return per-ticker signals for the configured ApeWisdom subreddits.

        Only tickers in ``known_symbols`` are kept (when provided) — ApeWisdom
        tracks every large-cap/meme name too, which is irrelevant noise for a
        small-cap scanner and would otherwise dominate the result set.
        """
        signals: Dict[str, RedditSignal] = {}
        for sub in self.cfg.apewisdom_subreddits:
            rows = self._fetch_filter(sub)
            for row in rows:
                ticker = str(row.get("ticker", "")).upper()
                if not ticker:
                    continue
                if known_symbols is not None and ticker not in known_symbols:
                    continue
                mentions = int(row.get("mentions", 0) or 0)
                mentions_24h_ago = int(row.get("mentions_24h_ago", 0) or 0)
                upvotes = int(row.get("upvotes", 0) or 0)

                sig = signals.get(ticker)
                if sig is None:
                    sig = signals[ticker] = RedditSignal(symbol=ticker)
                sig.mentions_total += mentions
                # ApeWisdom gives current vs 24h-ago mentions directly; the
                # net increase is a cleaner "is this heating up" signal than
                # we could derive ourselves from a single snapshot.
                sig.mentions_recent += max(0, mentions - mentions_24h_ago)
                sig.upvotes_sum += upvotes
                if sub not in sig.subreddits:
                    sig.subreddits.append(sub)
                if PROVIDER not in sig.providers:
                    sig.providers.append(PROVIDER)
        return signals
