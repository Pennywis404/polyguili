"""
Validation du calcul des fees contre la table officielle Polymarket.
Source: https://docs.polymarket.com/trading/fees
"""
from src.core.fees import calculate_fee, effective_fee_rate, shares_after_fee, arbitrage_profit


def test_fee_at_050():
    """100 shares a $0.50 -> fee ~ $0.78, rate = 1.56%"""
    fee = calculate_fee(100, 0.50, "crypto")
    assert abs(fee - 0.7813) < 0.01


def test_fee_at_045():
    """100 shares a $0.45 -> fee ~ $0.69"""
    fee = calculate_fee(100, 0.45, "crypto")
    assert abs(fee - 0.6891) < 0.01


def test_fee_at_010():
    """100 shares a $0.10 -> fee ~ $0.02"""
    fee = calculate_fee(100, 0.10, "crypto")
    assert abs(fee - 0.0203) < 0.02


def test_fee_rate_symmetry():
    """Le taux effectif est symetrique : rate(0.10) == rate(0.90)."""
    rate_10 = effective_fee_rate(0.10, "crypto")
    rate_90 = effective_fee_rate(0.90, "crypto")
    assert abs(rate_10 - rate_90) < 0.0001


def test_fee_at_zero():
    """Fee doit etre 0 a prix 0."""
    assert calculate_fee(100, 0.0, "crypto") == 0.0


def test_fee_at_one():
    """Fee doit etre 0 a prix 1."""
    assert calculate_fee(100, 1.0, "crypto") == 0.0


def test_effective_rate_at_050():
    """Taux effectif max a 0.50 = 1.5625%"""
    rate = effective_fee_rate(0.50, "crypto")
    assert abs(rate - 0.015625) < 0.001


def test_shares_after_fee():
    """Les shares apres fee doivent etre inferieures aux shares brutes."""
    gross = 100.0 / 0.50  # 200 shares
    net = shares_after_fee(100.0, 0.50, "crypto")
    assert net < gross
    assert net > 0


def test_arbitrage_profitable():
    """p1=0.45, p2=0.45 -> combined=0.90, doit etre profitable."""
    result = arbitrage_profit(0.45, 0.45, 1000, "crypto")
    assert result["is_profitable"] is True
    assert result["worst_case_roi"] > 8.0


def test_arbitrage_not_profitable():
    """p1=0.55, p2=0.50 -> combined=1.05, pas d'arbitrage."""
    result = arbitrage_profit(0.55, 0.50, 1000, "crypto")
    assert result["is_profitable"] is False


def test_optimal_sizing():
    """Le sizing proportionnel egalise les payouts."""
    result = arbitrage_profit(0.40, 0.48, 1000, "crypto")
    diff = abs(result["worst_case_profit"] - result["best_case_profit"])
    assert diff < 2.0
