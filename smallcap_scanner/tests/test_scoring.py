from smallcap_scanner.config import Config
from smallcap_scanner.models import RedditSignal, StockCandidate
from smallcap_scanner.pipeline import scan_combined, scan_fundamentals, scan_social
from smallcap_scanner import scoring


def _cfg() -> Config:
    return Config()


def test_low_diversity_triggers_pump_flag():
    stock = StockCandidate(symbol="PMPD", price=0.78, avg_volume=800_000)
    reddit = RedditSignal(
        symbol="PMPD", mentions_total=4, mentions_recent=4,
        unique_authors=1, upvotes_sum=10, subreddits=["pennystocks"],
        author_diversity_known=True,
    )
    flags = scoring.risk_flags(stock, reddit, _cfg())
    assert any("coordinated pump" in f for f in flags)
    assert any("SUB_$1" in f for f in flags)


def test_unknown_author_diversity_does_not_trigger_pump_flag():
    # ApeWisdom-style signal: no per-author data, so the pump heuristic
    # must not fire just because unique_authors defaults to 0.
    stock = StockCandidate(symbol="MEME", price=2.0, avg_volume=1_000_000)
    reddit = RedditSignal(
        symbol="MEME", mentions_total=50, mentions_recent=20, upvotes_sum=900,
        subreddits=["wallstreetbets"], providers=["apewisdom"],
    )
    flags = scoring.risk_flags(stock, reddit, _cfg())
    assert not any("pump" in f.lower() for f in flags)
    assert not any("SEEDED" in f for f in flags)


def test_organic_discussion_scores_higher_than_spam():
    organic = RedditSignal(
        symbol="AAA", mentions_total=6, mentions_recent=6, unique_authors=6,
        upvotes_sum=800, subreddits=["pennystocks", "smallstreetbets"],
        author_diversity_known=True,
    )
    spam = RedditSignal(
        symbol="BBB", mentions_total=6, mentions_recent=6, unique_authors=1,
        upvotes_sum=10, subreddits=["pennystocks"], author_diversity_known=True,
    )
    organic_score, _ = scoring.score_social(organic)
    spam_score, _ = scoring.score_social(spam)
    assert organic_score > spam_score


def test_uptrend_scores_higher_than_downtrend():
    up = StockCandidate(symbol="UP", price=2.0, price_avg_50=1.6,
                        price_avg_200=1.2, volume=3e6, avg_volume=1e6,
                        year_high=3.0, year_low=1.0)
    down = StockCandidate(symbol="DN", price=2.0, price_avg_50=2.4,
                          price_avg_200=2.8, volume=1e6, avg_volume=1e6,
                          year_high=5.0, year_low=1.9)
    up_score, _ = scoring.score_momentum(up)
    down_score, _ = scoring.score_momentum(down)
    assert up_score > down_score


def test_scan_fundamentals_includes_every_fmp_candidate_with_no_social_score():
    ranked = scan_fundamentals(_cfg(), mock=True, top_n=10)
    syms = {c.symbol for c in ranked}
    # FMP-only: every screened mock stock shows up, social-mentioned or not.
    assert syms == {"SLS", "GRND", "QTUM", "PMPD", "STBL"}
    assert all(c.social_score == 0.0 for c in ranked)
    assert all(c.reddit is None for c in ranked)


def test_scan_social_finds_tickers_outside_the_fmp_universe():
    signals = scan_social(_cfg(), mock=True)
    syms = {s.symbol for s in signals}
    assert "SLS" in syms
    # MOONX is only ever mentioned in mock posts, never in MOCK_STOCKS —
    # confirms stage 2 doesn't filter to the FMP-screened universe.
    assert "MOONX" in syms
    # Sorted by net-new mentions (all mock posts are "recent") desc.
    assert signals[0].mentions_recent >= signals[-1].mentions_recent


def test_scan_combined_only_contains_socially_discovered_tickers_and_flags_pump():
    ranked = scan_combined(_cfg(), mock=True, top_n=10)
    syms = [c.symbol for c in ranked]
    # QTUM/STBL are never mentioned in mock posts, so stage 3 (built from the
    # social list) never includes them even though they're FMP-screened.
    assert "QTUM" not in syms
    assert "STBL" not in syms
    assert "SLS" in syms
    # The multi-author, multi-subreddit SLS should outrank the single-spammer PMPD.
    pos = {c.symbol: i for i, c in enumerate(ranked)}
    assert pos["SLS"] < pos["PMPD"]
    pmpd = next(c for c in ranked if c.symbol == "PMPD")
    assert any("pump" in f.lower() for f in pmpd.flags)


def test_scan_combined_flags_ticker_outside_screen_range():
    ranked = scan_combined(_cfg(), mock=True, top_n=10)
    moonco = next(c for c in ranked if c.symbol == "MOONX")
    # MOONX ($42.50, $8.5B cap) is well outside the default price/cap band —
    # stage 3 surfaces it with full context rather than silently dropping it.
    assert "OUTSIDE_PRICE_RANGE" in moonco.flags
    assert "OUTSIDE_MARKET_CAP_RANGE" in moonco.flags
