from smallcap_scanner.apewisdom_client import ApeWisdomClient
from smallcap_scanner.config import Config
from smallcap_scanner.models import RedditSignal
from smallcap_scanner.reddit_aggregate import aggregate_from_posts, merge_signals
from smallcap_scanner.reddit_rss_client import _strip_html
import xml.etree.ElementTree as ET


SAMPLE_ATOM_ENTRY = """<entry xmlns="http://www.w3.org/2005/Atom">
<author><name>/u/diamondhands1</name></author>
<content type="html">&lt;div&gt;$SLS to the moon, six months of grinding&lt;/div&gt;</content>
<id>t3_abc123</id>
<link href="https://www.reddit.com/r/pennystocks/comments/abc123/sls/" />
<published>2026-06-30T04:01:02+00:00</published>
<title>SLS DD - why this runs</title>
</entry>"""


def test_strip_html_unescapes_and_removes_tags():
    raw = "&lt;div&gt;$SLS &amp; friends&lt;/div&gt;"
    assert _strip_html(raw) == " $SLS & friends "


def test_atom_entry_fields_parse_as_expected():
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = ET.fromstring(SAMPLE_ATOM_ENTRY)
    title = entry.find("atom:title", ns).text
    author = entry.find("atom:author/atom:name", ns).text
    content = _strip_html(entry.find("atom:content", ns).text)
    assert title == "SLS DD - why this runs"
    assert author == "/u/diamondhands1"
    assert "$SLS" in content


def test_aggregate_from_posts_marks_author_diversity_known():
    posts = [
        {"title": "$SLS to the moon", "selftext": "", "author": "a",
         "score": 10, "created_utc": 9_999_999_999, "subreddit": "pennystocks"},
        {"title": "$SLS again", "selftext": "", "author": "b",
         "score": 5, "created_utc": 9_999_999_999, "subreddit": "pennystocks"},
    ]
    signals = aggregate_from_posts(posts, {"SLS"}, 72, provider="reddit_rss")
    sig = signals["SLS"]
    assert sig.author_diversity_known is True
    assert sig.unique_authors == 2
    assert sig.mentions_total == 2
    assert "reddit_rss" in sig.providers


def test_merge_signals_combines_counts_and_keeps_known_flag_only_if_all_known():
    rss_sig = {
        "SLS": RedditSignal(
            symbol="SLS", mentions_total=3, mentions_recent=3, unique_authors=3,
            upvotes_sum=50, subreddits=["pennystocks"], providers=["reddit_rss"],
            author_diversity_known=True,
        )
    }
    ape_sig = {
        "SLS": RedditSignal(
            symbol="SLS", mentions_total=10, mentions_recent=4, upvotes_sum=200,
            subreddits=["wallstreetbets"], providers=["apewisdom"],
            author_diversity_known=False,
        )
    }
    merged = merge_signals(rss_sig, ape_sig)
    sig = merged["SLS"]
    assert sig.mentions_total == 13
    assert sig.upvotes_sum == 250
    assert set(sig.subreddits) == {"pennystocks", "wallstreetbets"}
    assert set(sig.providers) == {"reddit_rss", "apewisdom"}
    # Mixed known/unknown sources -> overall diversity treated as not known.
    assert sig.author_diversity_known is False


def test_merge_signals_keeps_known_true_when_all_sources_known():
    a = {"X": RedditSignal(symbol="X", mentions_total=1, unique_authors=1,
                            author_diversity_known=True)}
    b = {"X": RedditSignal(symbol="X", mentions_total=1, unique_authors=1,
                            author_diversity_known=True)}
    merged = merge_signals(a, b)
    assert merged["X"].author_diversity_known is True


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
