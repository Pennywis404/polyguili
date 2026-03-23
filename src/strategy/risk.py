"""
Fonctions pures de validation pre-trade.
Chaque check retourne un bool, validate_trade les agrege.
"""
from datetime import datetime

from src.core.models import MarketPair, PaperTrade, PortfolioState

MAX_PORTFOLIO_EXPOSURE = 0.5
MAX_PER_ASSET = 0.25
MAX_LOSS_PER_TRADE = 0.02


def check_capital_available(portfolio: PortfolioState, amount: float) -> bool:
    return portfolio.current_capital >= amount


def check_max_positions(portfolio: PortfolioState, max_pos: int) -> bool:
    return len(portfolio.active_positions) < max_pos


def check_portfolio_exposure(portfolio: PortfolioState, max_pct: float = MAX_PORTFOLIO_EXPOSURE) -> bool:
    if portfolio.initial_capital <= 0:
        return False
    return portfolio.total_deployed / portfolio.initial_capital < max_pct


def check_asset_concentration(
    trades: dict[str, PaperTrade],
    active_ids: list[str],
    asset: str,
    initial_capital: float,
    max_pct: float = MAX_PER_ASSET,
) -> bool:
    deployed_on_asset = sum(
        t.capital_deployed
        for tid in active_ids
        if (t := trades.get(tid)) and t.asset == asset
    )
    if initial_capital <= 0:
        return False
    return deployed_on_asset / initial_capital < max_pct


def check_time_to_resolution(pair: MarketPair, min_seconds: int) -> bool:
    remaining = (pair.resolution_time - datetime.utcnow()).total_seconds()
    return remaining >= min_seconds


def check_liquidity(pair: MarketPair, min_usdc: float) -> bool:
    return pair.ask_size_up >= min_usdc and pair.ask_size_down >= min_usdc


def validate_trade(
    pair: MarketPair,
    capital_needed: float,
    portfolio: PortfolioState,
    trades: dict[str, PaperTrade],
    max_positions: int,
    min_time: int,
    min_liquidity: float,
) -> tuple[bool, str]:
    """Agrege tous les checks. Retourne (ok, raison_refus)."""
    if not check_capital_available(portfolio, capital_needed):
        return False, f"Capital insuffisant ({portfolio.current_capital:.2f} < {capital_needed:.2f})"

    if not check_max_positions(portfolio, max_positions):
        return False, f"Max positions atteint ({len(portfolio.active_positions)}/{max_positions})"

    if not check_portfolio_exposure(portfolio):
        return False, f"Exposition portfolio trop elevee ({portfolio.total_deployed / portfolio.initial_capital:.0%})"

    if not check_asset_concentration(trades, portfolio.active_positions, pair.asset, portfolio.initial_capital):
        return False, f"Concentration {pair.asset} trop elevee"

    if not check_time_to_resolution(pair, min_time):
        remaining = (pair.resolution_time - datetime.utcnow()).total_seconds()
        return False, f"Trop proche de la resolution ({remaining:.0f}s < {min_time}s)"

    if not check_liquidity(pair, min_liquidity):
        return False, f"Liquidite insuffisante (up={pair.ask_size_up:.0f}, down={pair.ask_size_down:.0f})"

    return True, "OK"
