"""Scan subreddits for ticker mentions via PRAW (official Reddit OAuth).

This is the fully ToS-compliant path and the only one that can reach
*every* subreddit in ``cfg.subreddits`` (including the niche ones ApeWisdom
doesn't track) without relying on Reddit's public RSS feeds. Use it by
setting ``REDDIT_MODE=praw`` plus ``REDDIT_CLIENT_ID``/``REDDIT_CLIENT_SECRET``
from a "script" app at https://www.reddit.com/prefs/apps.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from .config import Config
from .models import RedditSignal
from .reddit_aggregate import aggregate_from_posts

log = logging.getLogger(__name__)

PROVIDER = "reddit_praw"


class RedditScanner:
    def __init__(self, config: Config):
        if not (config.reddit_client_id and config.reddit_client_secret):
            raise RuntimeError(
                "Reddit credentials missing. Set REDDIT_CLIENT_ID and "
                "REDDIT_CLIENT_SECRET (create a 'script' app at "
                "https://www.reddit.com/prefs/apps), or use the default "
                "REDDIT_MODE=auto which needs no credentials."
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

    def scan(self, known_symbols: Optional[Set[str]] = None) -> Dict[str, RedditSignal]:
        posts: List[dict] = []
        for sub in self.cfg.subreddits:
            try:
                posts.extend(self._fetch_subreddit(sub))
            except Exception as exc:  # one bad sub shouldn't kill the whole run
                log.warning("error scanning r/%s: %s", sub, exc)
        return aggregate_from_posts(
            posts, known_symbols, self.cfg.reddit_lookback_hours, PROVIDER
        )

    def _fetch_subreddit(self, sub: str) -> List[dict]:
        subreddit = self.reddit.subreddit(sub)
        limit = self.cfg.reddit_post_limit
        seen_ids: Set[str] = set()
        posts: List[dict] = []
        # Combine 'new' (recency) and 'hot' (traction) for a fuller picture.
        for listing in (subreddit.new(limit=limit), subreddit.hot(limit=limit)):
            for post in listing:
                if post.id in seen_ids:
                    continue
                seen_ids.add(post.id)
                posts.append(
                    {
                        "title": post.title,
                        "selftext": getattr(post, "selftext", "") or "",
                        "author": str(post.author) if post.author else "[deleted]",
                        "score": int(getattr(post, "score", 0) or 0),
                        "created_utc": post.created_utc,
                        "subreddit": sub,
                    }
                )
        return posts
