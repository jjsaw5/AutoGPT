from smallcap_scanner.config import Config
from smallcap_scanner.models import RedditSignal, StockCandidate
from smallcap_scanner.pipeline import run_scan
from smallcap_scanner import scoring


def _cfg() -> Config:
    return Config()


def test_low_diversity_triggers_pump_flag():
    stock = StockCandidate(symbol="PMPD", price=0.78, avg_volume=800_000)
    reddit = RedditSignal(
        symbol="PMPD", mentions_total=4, mentions_recent=4,
        unique_authors=1, upvotes_sum=10, subreddits=["pennystocks"],
    )
    flags = scoring.risk_flags(stock, reddit, _cfg())
    assert any("coordinated pump" in f for f in flags)
    assert any("SUB_$1" in f for f in flags)


def test_organic_discussion_scores_higher_than_spam():
    organic = RedditSignal(
        symbol="AAA", mentions_total=6, mentions_recent=6, unique_authors=6,
        upvotes_sum=800, subreddits=["pennystocks", "smallstreetbets"],
    )
    spam = RedditSignal(
        symbol="BBB", mentions_total=6, mentions_recent=6, unique_authors=1,
        upvotes_sum=10, subreddits=["pennystocks"],
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


def test_mock_pipeline_ranks_and_flags():
    ranked = run_scan(_cfg(), mock=True, top_n=10)
    syms = [c.symbol for c in ranked]
    assert "SLS" in syms
    # The multi-author, multi-subreddit SLS should outrank the single-spammer PMPD.
    pos = {c.symbol: i for i, c in enumerate(ranked)}
    assert pos["SLS"] < pos["PMPD"]
    pmpd = next(c for c in ranked if c.symbol == "PMPD")
    assert any("pump" in f.lower() for f in pmpd.flags)


def test_require_social_filters_out_silent_names():
    ranked = run_scan(_cfg(), mock=True, require_social=True, top_n=10)
    syms = {c.symbol for c in ranked}
    # STBL and QTUM have no mock Reddit mentions.
    assert "STBL" not in syms
    assert "SLS" in syms
