import pytest

from odte.config import ContractConfig, RiskConfig
from odte.contract import NoContractFound, select_contract, size_position
from odte.models import OptionContract


def contract(strike, kind="call", bid=2.00, ask=2.06, delta=0.40, oi=1000, vol=500):
    return OptionContract(
        symbol="SPY",
        expiration="2026-07-31",
        strike=strike,
        option_type=kind,
        bid=bid,
        ask=ask,
        delta=delta,
        open_interest=oi,
        volume=vol,
    )


def test_mid_and_spread_pct():
    c = contract(740, bid=2.00, ask=2.10)
    assert c.mid == pytest.approx(2.05)
    assert c.spread_pct == pytest.approx(0.10 / 2.05)


def test_selects_the_contract_nearest_target_delta():
    picked = select_contract(
        [
            contract(745, delta=0.25),
            contract(742, delta=0.38),
            contract(738, delta=0.60),
        ],
        direction=1,
    )
    assert picked.strike == 742


def test_wide_spreads_are_excluded():
    with pytest.raises(NoContractFound):
        select_contract([contract(740, bid=2.00, ask=2.40)], direction=1)


def test_illiquid_contracts_are_excluded():
    with pytest.raises(NoContractFound):
        select_contract([contract(740, oi=10, vol=5)], direction=1)


def test_delta_outside_the_band_is_excluded():
    with pytest.raises(NoContractFound):
        select_contract([contract(760, delta=0.05)], direction=1)


def test_direction_picks_the_right_option_type():
    chain = [contract(740, kind="call"), contract(735, kind="put", delta=-0.40)]
    assert select_contract(chain, direction=1).option_type == "call"
    assert select_contract(chain, direction=-1).option_type == "put"


def test_puts_are_matched_on_absolute_delta():
    picked = select_contract(
        [
            contract(730, kind="put", delta=-0.20),
            contract(735, kind="put", delta=-0.42),
        ],
        direction=-1,
    )
    assert picked.strike == 735


def test_falls_back_to_tightest_spread_without_greeks():
    picked = select_contract(
        [
            contract(740, bid=2.00, ask=2.10, delta=None),
            contract(741, bid=2.00, ask=2.02, delta=None),
        ],
        direction=1,
    )
    assert picked.strike == 741


def test_size_is_derived_from_dollar_risk():
    # $250 risk, $2.05 premium, 25% stop -> $51.25 risk per contract -> 4
    quantity, risked = size_position(
        contract(740, bid=2.00, ask=2.10), 250.0, RiskConfig()
    )
    assert quantity == 4
    assert risked == pytest.approx(205.0)


def test_size_respects_the_contract_cap():
    quantity, _ = size_position(contract(740, bid=0.10, ask=0.10), 250.0, RiskConfig())
    assert quantity == RiskConfig().max_contracts


def test_expensive_premium_can_size_to_zero_rather_than_rounding_up():
    quantity, risked = size_position(
        contract(740, bid=4.00, ask=4.04), 50.0, RiskConfig()
    )
    assert quantity == 0
    assert risked == 0.0


def test_premium_cap_excludes_expensive_contracts():
    config = ContractConfig(max_premium=1.00)
    with pytest.raises(NoContractFound):
        select_contract([contract(740, bid=3.00, ask=3.05)], direction=1, config=config)
