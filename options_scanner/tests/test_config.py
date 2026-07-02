from options_scanner.config import load_config
from options_scanner.models import CapTier


def test_config_loads_core_knobs():
    cfg = load_config(load_env=False)
    assert cfg.account["size"] == 5000
    assert cfg.account["max_open_risk"] == 2000
    assert cfg.account["max_positions"] == 6
    assert cfg.go_threshold == 72
    assert cfg.watch_threshold == 58
    assert cfg.weights == {"P1": 25, "P2": 22, "P3": 20, "P4": 18, "P5": 10, "P6": 5}


def test_weights_sum_to_100():
    cfg = load_config(load_env=False)
    assert sum(cfg.weights.values()) == 100


def test_cap_tier_from_market_cap():
    assert CapTier.from_market_cap(250e9) == CapTier.MEGA
    assert CapTier.from_market_cap(50e9) == CapTier.LARGE
    assert CapTier.from_market_cap(5e9) == CapTier.MID
    assert CapTier.from_market_cap(1e9) == CapTier.SMALL
    assert CapTier.from_market_cap(100e6) == CapTier.MICRO
    assert CapTier.from_market_cap(None) is None
