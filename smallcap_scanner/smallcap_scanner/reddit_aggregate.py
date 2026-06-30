"""Shared aggregation logic: raw posts -> per-ticker RedditSignal.

Used by both the RSS provider (real per-post data, author-diversity-aware)
and the mock data set. Kept provider-agnostic so scoring never has to know
where the posts came from.
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


def merge_signals(*signal_maps: Dict[str, RedditSignal]) -> Dict[str, RedditSignal]:
    """Combine per-ticker signals from multiple providers.

    Author-diversity counts are only meaningfully comparable within a single
    provider's data, so when merging we sum the raw counts (a reasonable
    approximation for ranking) but only mark the merged signal
    ``author_diversity_known`` if every contributing source for that ticker
    tracked authors — otherwise diversity-based scoring/flags stay neutral
    rather than penalizing a ticker just because one of its sources doesn't
    track authors.
    """
    merged: Dict[str, RedditSignal] = {}
    for smap in signal_maps:
        for sym, sig in smap.items():
            m = merged.get(sym)
            if m is None:
                merged[sym] = RedditSignal(
                    symbol=sym,
                    mentions_total=sig.mentions_total,
                    mentions_recent=sig.mentions_recent,
                    unique_authors=sig.unique_authors,
                    upvotes_sum=sig.upvotes_sum,
                    subreddits=list(sig.subreddits),
                    sample_titles=list(sig.sample_titles),
                    providers=list(sig.providers),
                    author_diversity_known=sig.author_diversity_known,
                )
                continue
            m.mentions_total += sig.mentions_total
            m.mentions_recent += sig.mentions_recent
            m.unique_authors += sig.unique_authors
            m.upvotes_sum += sig.upvotes_sum
            for s in sig.subreddits:
                if s not in m.subreddits:
                    m.subreddits.append(s)
            for t in sig.sample_titles:
                if len(m.sample_titles) < 5:
                    m.sample_titles.append(t)
            for p in sig.providers:
                if p not in m.providers:
                    m.providers.append(p)
            m.author_diversity_known = m.author_diversity_known and sig.author_diversity_known
    return merged
