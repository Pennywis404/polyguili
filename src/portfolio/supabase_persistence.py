"""
Persistance Supabase — remplace la persistance JSON.
Sauvegarde l'etat du bot dans Supabase (trades, opportunities, portfolio).
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from src.core.models import Opportunity, PaperTrade, PortfolioState, Side, TradeStatus

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def _trade_to_row(trade: PaperTrade) -> dict:
    return {
        "id": trade.id,
        "pair_id": trade.pair_id,
        "asset": trade.asset,
        "timeframe": trade.timeframe,
        "leg1_side": trade.leg1_side.value,
        "leg1_price": trade.leg1_price,
        "leg1_shares": trade.leg1_shares,
        "leg1_fee": trade.leg1_fee,
        "leg1_timestamp": trade.leg1_timestamp.isoformat(),
        "leg1_stake": trade.leg1_stake,
        "leg2_side": trade.leg2_side.value if trade.leg2_side else None,
        "leg2_price": trade.leg2_price,
        "leg2_shares": trade.leg2_shares,
        "leg2_fee": trade.leg2_fee,
        "leg2_timestamp": trade.leg2_timestamp.isoformat() if trade.leg2_timestamp else None,
        "leg2_stake": trade.leg2_stake,
        "status": trade.status.value,
        "capital_deployed": trade.capital_deployed,
        "total_fees": trade.total_fees,
        "payout": trade.payout,
        "profit": trade.profit,
        "roi": trade.roi,
        "resolution_outcome": trade.resolution_outcome,
        "resolved_at": trade.resolved_at.isoformat() if trade.resolved_at else None,
        "resolution_time": trade.resolution_time.isoformat() if trade.resolution_time else None,
    }


def _row_to_trade(row: dict) -> PaperTrade:
    return PaperTrade(
        id=row["id"],
        pair_id=row["pair_id"],
        asset=row["asset"],
        timeframe=row["timeframe"],
        leg1_side=Side(row["leg1_side"]),
        leg1_price=row["leg1_price"],
        leg1_shares=row["leg1_shares"],
        leg1_fee=row["leg1_fee"],
        leg1_timestamp=datetime.fromisoformat(row["leg1_timestamp"]),
        leg1_stake=row["leg1_stake"],
        leg2_side=Side(row["leg2_side"]) if row.get("leg2_side") else None,
        leg2_price=row.get("leg2_price"),
        leg2_shares=row.get("leg2_shares"),
        leg2_fee=row.get("leg2_fee"),
        leg2_timestamp=datetime.fromisoformat(row["leg2_timestamp"]) if row.get("leg2_timestamp") else None,
        leg2_stake=row.get("leg2_stake"),
        status=TradeStatus(row["status"]),
        capital_deployed=row.get("capital_deployed", 0),
        total_fees=row.get("total_fees", 0),
        payout=row.get("payout"),
        profit=row.get("profit"),
        roi=row.get("roi"),
        resolution_outcome=row.get("resolution_outcome"),
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row.get("resolved_at") else None,
        resolution_time=datetime.fromisoformat(row["resolution_time"]) if row.get("resolution_time") else None,
    )


def _opp_to_row(opp: Opportunity) -> dict:
    return {
        "id": opp.id,
        "pair_id": opp.pair_id,
        "asset": opp.asset,
        "timeframe": opp.timeframe,
        "leg1_side": opp.leg1_side.value,
        "leg1_price": opp.leg1_price,
        "leg2_price": opp.leg2_price,
        "timestamp": opp.timestamp.isoformat(),
        "combined_cost": opp.combined_cost,
        "estimated_profit_pct": opp.estimated_profit_pct,
        "available_liquidity": opp.available_liquidity,
        "status": opp.status,
    }


def _row_to_opp(row: dict) -> Opportunity:
    return Opportunity(
        id=row["id"],
        pair_id=row["pair_id"],
        asset=row["asset"],
        timeframe=row["timeframe"],
        leg1_side=Side(row["leg1_side"]),
        leg1_price=row["leg1_price"],
        leg2_price=row["leg2_price"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        combined_cost=row["combined_cost"],
        estimated_profit_pct=row["estimated_profit_pct"],
        available_liquidity=row["available_liquidity"],
        status=row.get("status", "detected"),
    )


class SupabasePersistence:
    """Gere la persistance dans Supabase."""

    def __init__(self) -> None:
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = _get_client()
        return self._client

    # --- Portfolio State ---

    def load_portfolio(self, default_capital: float = 10000.0) -> PortfolioState:
        try:
            resp = self.client.table("portfolio_state").select("*").eq("id", 1).execute()
            if resp.data:
                row = resp.data[0]
                return PortfolioState(
                    initial_capital=row["initial_capital"],
                    current_capital=row["current_capital"],
                    total_deployed=row["total_deployed"],
                    total_pnl=row["total_pnl"],
                    total_fees_paid=row["total_fees_paid"],
                    total_trades=row["total_trades"],
                    winning_trades=row["winning_trades"],
                    losing_trades=row["losing_trades"],
                    active_positions=row.get("active_positions", []),
                )
        except Exception as e:
            logger.error("Failed to load portfolio from Supabase: %s", e)

        return PortfolioState(initial_capital=default_capital, current_capital=default_capital)

    def save_portfolio(self, portfolio: PortfolioState) -> None:
        try:
            self.client.table("portfolio_state").upsert({
                "id": 1,
                "initial_capital": portfolio.initial_capital,
                "current_capital": portfolio.current_capital,
                "total_deployed": portfolio.total_deployed,
                "total_pnl": portfolio.total_pnl,
                "total_fees_paid": portfolio.total_fees_paid,
                "total_trades": portfolio.total_trades,
                "winning_trades": portfolio.winning_trades,
                "losing_trades": portfolio.losing_trades,
                "active_positions": portfolio.active_positions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.error("Failed to save portfolio to Supabase: %s", e)

    # --- Trades ---

    def load_trades(self) -> dict[str, PaperTrade]:
        try:
            resp = self.client.table("trades").select("*").execute()
            trades = {}
            for row in resp.data:
                try:
                    trade = _row_to_trade(row)
                    trades[trade.id] = trade
                except Exception as e:
                    logger.warning("Failed to parse trade %s: %s", row.get("id"), e)
            return trades
        except Exception as e:
            logger.error("Failed to load trades from Supabase: %s", e)
            return {}

    def save_trade(self, trade: PaperTrade) -> None:
        try:
            self.client.table("trades").upsert(_trade_to_row(trade)).execute()
        except Exception as e:
            logger.error("Failed to save trade %s: %s", trade.id, e)

    # --- Opportunities ---

    def load_opportunities(self, limit: int = 100) -> list[Opportunity]:
        try:
            resp = (
                self.client.table("opportunities")
                .select("*")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            opps = []
            for row in resp.data:
                try:
                    opps.append(_row_to_opp(row))
                except Exception as e:
                    logger.warning("Failed to parse opportunity: %s", e)
            return list(reversed(opps))
        except Exception as e:
            logger.error("Failed to load opportunities from Supabase: %s", e)
            return []

    def save_opportunity(self, opp: Opportunity) -> None:
        try:
            self.client.table("opportunities").upsert(_opp_to_row(opp)).execute()
        except Exception as e:
            logger.error("Failed to save opportunity %s: %s", opp.id, e)


def save_state(
    persistence: SupabasePersistence,
    portfolio: PortfolioState,
    trades: dict[str, PaperTrade],
    opportunities: list,
) -> None:
    """Sauvegarde complete de l'etat dans Supabase."""
    persistence.save_portfolio(portfolio)
    for trade in trades.values():
        persistence.save_trade(trade)
    for opp in list(opportunities)[-100:]:
        if isinstance(opp, Opportunity):
            persistence.save_opportunity(opp)


def load_state(
    persistence: SupabasePersistence,
    default_capital: float = 10000.0,
) -> tuple[PortfolioState, dict[str, PaperTrade], list[Opportunity]]:
    """Charge l'etat complet depuis Supabase."""
    portfolio = persistence.load_portfolio(default_capital)
    trades = persistence.load_trades()
    opportunities = persistence.load_opportunities()
    logger.info(
        "Supabase state loaded: capital=$%.2f, %d trades, %d opportunities",
        portfolio.current_capital, len(trades), len(opportunities),
    )
    return portfolio, trades, opportunities


async def auto_save_loop(
    persistence: SupabasePersistence,
    portfolio: PortfolioState,
    trades: dict[str, PaperTrade],
    opportunities: list,
    interval: int = 60,
) -> None:
    """Tache asyncio qui sauvegarde l'etat periodiquement dans Supabase."""
    logger.info("Supabase auto-save loop started (every %ds)", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            save_state(persistence, portfolio, trades, opportunities)
        except Exception as e:
            logger.error("Supabase auto-save failed: %s", e)
