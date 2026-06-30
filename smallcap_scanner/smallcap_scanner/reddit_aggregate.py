"""Shared aggregation logic: raw posts -> per-ticker RedditSignal.

Used by the PRAW provider (real per-post data, author-diversity-aware) and
the mock data set. Kept provider-agnostic so scoring never has to know where
the posts came from.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from .models import RedditSignal
from .ticker_extract import extract_tickers


def aggregate_from_posts(
    posts: List[dict],
    known_symbols: Optional[Set[str]],
    lookback_hours: int,
    provider: str,
) -> Dict[str, RedditSignal]:
    """Aggregate post dicts into per-ticker signals with author tracking.

    Each post dict needs: title, selftext, author, score, created_utc,
    subreddit. Use this for sources that expose individual posts (RSS); for
    aggregate-only sources (ApeWisdom) build ``RedditSignal`` directly instead
    since there's no author data to track.
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
                sig = signals[sym] = RedditSignal(symbol=sym, author_diversity_known=True)
                authors[sym] = set()
            sig.mentions_total += 1
            if recent:
                sig.mentions_recent += 1
            sig.upvotes_sum += int(post.get("score", 0) or 0)
            if sub and sub not in sig.subreddits:
                sig.subreddits.append(sub)
            if provider not in sig.providers:
                sig.providers.append(provider)
            if len(sig.sample_titles) < 3:
                sig.sample_titles.append(str(post.get("title", ""))[:140])
            authors[sym].add(author)

    for sym, sig in signals.items():
        sig.unique_authors = len(authors.get(sym, ()))
    return signals
