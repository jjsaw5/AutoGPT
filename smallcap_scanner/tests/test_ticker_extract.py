from smallcap_scanner.ticker_extract import extract_tickers


def test_cashtag_accepted_even_if_unknown():
    assert extract_tickers("buying $SLS calls today") == ["SLS"]


def test_bare_token_requires_known_symbol():
    # Without a known set, bare uppercase tokens are ignored (too noisy).
    assert extract_tickers("SLS to the moon") == []
    # With a known set, the bare token is picked up.
    assert extract_tickers("SLS to the moon", {"SLS"}) == ["SLS"]


def test_stopwords_filtered():
    text = "the CEO said YOLO DD on the IPO, USA USA"
    assert extract_tickers(text, {"CEO", "USA"}) == []


def test_dedupes_and_preserves_order():
    text = "$GRND then $SLS then GRND again"
    assert extract_tickers(text, {"GRND", "SLS"}) == ["GRND", "SLS"]


def test_share_class_suffix():
    assert extract_tickers("$BRK.B is pricey") == ["BRK"]


def test_empty_input():
    assert extract_tickers("") == []
    assert extract_tickers(None) == []  # type: ignore[arg-type]
