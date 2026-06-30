from smallcap_scanner.apewisdom_client import ApeWisdomClient
from smallcap_scanner.config import Config
from smallcap_scanner.reddit_aggregate import aggregate_from_posts


def test_aggregate_from_posts_marks_author_diversity_known():
    posts = [
        {"title": "$SLS to the moon", "selftext": "", "author": "a",
         "score": 10, "created_utc": 9_999_999_999, "subreddit": "pennystocks"},
        {"title": "$SLS again", "selftext": "", "author": "b",
         "score": 5, "created_utc": 9_999_999_999, "subreddit": "pennystocks"},
    ]
    signals = aggregate_from_posts(posts, {"SLS"}, 72, provider="reddit_praw")
    sig = signals["SLS"]
    assert sig.author_diversity_known is True
    assert sig.unique_authors == 2
    assert sig.mentions_total == 2
    assert "reddit_praw" in sig.providers


def test_apewisdom_filters_to_known_symbols_and_computes_recent_delta(monkeypatch):
    client = ApeWisdomClient(Config())
    fake_rows = {
        "wallstreetbets": [
            {"ticker": "SLS", "mentions": 50, "mentions_24h_ago": 20, "upvotes": 900},
            {"ticker": "AAPL", "mentions": 1000, "mentions_24h_ago": 900, "upvotes": 5000},
        ]
    }
    monkeypatch.setattr(client, "_fetch_filter", lambda sub: fake_rows.get(sub, []))
    client.cfg.apewisdom_subreddits = ["wallstreetbets"]

    signals = client.scan(known_symbols={"SLS"})

    assert set(signals) == {"SLS"}  # AAPL dropped — not in the small-cap universe
    sig = signals["SLS"]
    assert sig.mentions_total == 50
    assert sig.mentions_recent == 30  # 50 - 20 net-new
    assert sig.upvotes_sum == 900
    assert sig.author_diversity_known is False
    assert "apewisdom" in sig.providers


def test_apewisdom_no_filter_returns_everything(monkeypatch):
    # Stage 2 (raw social discovery) deliberately passes known_symbols=None
    # so it isn't limited to tickers that already passed the FMP screen.
    client = ApeWisdomClient(Config())
    fake_rows = {
        "wallstreetbets": [
            {"ticker": "SLS", "mentions": 50, "mentions_24h_ago": 20, "upvotes": 900},
            {"ticker": "AAPL", "mentions": 1000, "mentions_24h_ago": 900, "upvotes": 5000},
        ]
    }
    monkeypatch.setattr(client, "_fetch_filter", lambda sub: fake_rows.get(sub, []))
    client.cfg.apewisdom_subreddits = ["wallstreetbets"]

    signals = client.scan(known_symbols=None)

    assert set(signals) == {"SLS", "AAPL"}
