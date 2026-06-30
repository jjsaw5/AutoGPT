"""Scan the configured subreddits for ticker mentions via PRAW.

Uses Reddit's read-only "script" app auth (client id + secret, no user login),
which is sufficient for reading public subreddits. Register an app at
https://www.reddit.com/prefs/apps (type: "script").
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Set

from .config import Config
from .models import RedditSignal
from .ticker_extract import extract_tickers

log = logging.getLogger(__name__)


class RedditScanner:
    def __init__(self, config: Config):
        if not config.has_reddit:
            raise RuntimeError(
                "Reddit credentials missing. Set REDDIT_CLIENT_ID and "
                "REDDIT_CLIENT_SECRET (create a 'script' app at "
                "https://www.reddit.com/prefs/apps)."
            )
        import praw  # imported lazily so the package works without it installed

        self.cfg = config
        self.reddit = praw.Reddit(
            client_id=config.reddit_client_id,
            client_secret=config.reddit_client_secret,
            user_agent=config.reddit_user_agent,
            check_for_async=False,
        )
        self.reddit.read_only = True

    def scan(self, known_symbols: Set[str] | None = None) -> Dict[str, RedditSignal]:
        cutoff = time.time() - self.cfg.reddit_lookback_hours * 3600
        signals: Dict[str, RedditSignal] = {}
        # track authors per symbol without storing them on the public model
        authors: Dict[str, Set[str]] = {}

        for sub in self.cfg.subreddits:
            try:
                self._scan_subreddit(sub, cutoff, known_symbols, signals, authors)
            except Exception as exc:  # one bad sub shouldn't kill the whole run
                log.warning("error scanning r/%s: %s", sub, exc)

        for sym, sig in signals.items():
            sig.unique_authors = len(authors.get(sym, ()))
        return signals

    def _scan_subreddit(
        self,
        sub: str,
        cutoff: float,
        known_symbols: Set[str] | None,
        signals: Dict[str, RedditSignal],
        authors: Dict[str, Set[str]],
    ) -> None:
        subreddit = self.reddit.subreddit(sub)
        limit = self.cfg.reddit_post_limit
        # Combine 'new' (recency) and 'hot' (traction) for a fuller picture.
        seen_ids: Set[str] = set()
        listings = [subreddit.new(limit=limit), subreddit.hot(limit=limit)]

        for listing in listings:
            for post in listing:
                if post.id in seen_ids:
                    continue
                seen_ids.add(post.id)

                recent = post.created_utc >= cutoff
                text = f"{post.title}\n{getattr(post, 'selftext', '') or ''}"
                author = str(post.author) if post.author else "[deleted]"
                tickers = extract_tickers(text, known_symbols)

                for sym in tickers:
                    sig = signals.get(sym)
                    if sig is None:
                        sig = signals[sym] = RedditSignal(symbol=sym)
                        authors[sym] = set()
                    sig.mentions_total += 1
                    if recent:
                        sig.mentions_recent += 1
                    sig.upvotes_sum += int(getattr(post, "score", 0) or 0)
                    if sub not in sig.subreddits:
                        sig.subreddits.append(sub)
                    if len(sig.sample_titles) < 3:
                        sig.sample_titles.append(post.title[:140])
                    authors[sym].add(author)


def aggregate_from_posts(
    posts: List[dict], known_symbols: Set[str] | None, lookback_hours: int
) -> Dict[str, RedditSignal]:
    """Pure aggregation helper used by tests and the mock provider.

    ``posts`` is a list of dicts with keys: title, selftext, author, score,
    created_utc, subreddit.
    """
    cutoff = time.time() - lookback_hours * 3600
    signals: Dict[str, RedditSignal] = {}
    authors: Dict[str, Set[str]] = {}
    for post in posts:
        text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
        recent = float(post.get("created_utc", 0)) >= cutoff
        author = post.get("author") or "[deleted]"
        sub = post.get("subreddit", "")
        for sym in extract_tickers(text, known_symbols):
            sig = signals.get(sym)
            if sig is None:
                sig = signals[sym] = RedditSignal(symbol=sym)
                authors[sym] = set()
            sig.mentions_total += 1
            if recent:
                sig.mentions_recent += 1
            sig.upvotes_sum += int(post.get("score", 0) or 0)
            if sub and sub not in sig.subreddits:
                sig.subreddits.append(sub)
            if len(sig.sample_titles) < 3:
                sig.sample_titles.append(str(post.get("title", ""))[:140])
            authors[sym].add(author)
    for sym, sig in signals.items():
        sig.unique_authors = len(authors.get(sym, ()))
    return signals
