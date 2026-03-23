"""
Paper execution engine.
Ecoute les opportunites detectees, valide les risques, et simule les trades.
Gere aussi la resolution des marches (payout).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.fees import arbitrage_profit, shares_after_fee
from src.core.models import (
    MarketPair,
    Opportunity,
    PaperTrade,
    PortfolioState,
    Side,
    TradeStatus,
)
from src.strategy.risk import validate_trade

logger = logging.getLogger(__name__)


class PaperExecutor:
    def __init__(
        self,
        event_bus: EventBus,
        portfolio: PortfolioState,
        trades: dict[str, PaperTrade],
        pairs_ref: list[MarketPair],
        capital_per_trade: float = 100.0,
        max_concurrent_positions: int = 5,
        min_time_to_resolution: int = 120,
        min_liquidity: float = 50.0,
    ) -> None:
        self._event_bus = event_bus
        self.portfolio = portfolio
        self.trades = trades
        self._pairs_ref = pairs_ref
        self._capital_per_trade = capital_per_trade
        self._max_positions = max_concurrent_positions
        self._min_time = min_time_to_resolution
        self._min_liquidity = min_liquidity
        self._running = False

    async def run(self) -> None:
        """Boucle principale : ecoute les opportunites et gere les resolutions."""
        self._running = True
        queue = await self._event_bus.subscribe()
        logger.info("PaperExecutor started (capital: $%.2f)", self.portfolio.current_capital)

        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                if event.type == "opportunity_detected":
                    await self._handle_opportunity(event)
                elif event.type == "price_update":
                    await self._check_resolutions()
            except asyncio.TimeoutError:
                await self._check_resolutions()
            except Exception as e:
                logger.error("Executor error: %s", e, exc_info=True)

    def stop(self) -> None:
        self._running = False

    async def _handle_opportunity(self, event: Event) -> None:
        """Traite une opportunite detectee."""
        opp = Opportunity.from_dict(event.data)

        # Trouver la paire
        pair = self._find_pair(opp.pair_id)
        if not pair:
            logger.warning("Pair not found for opportunity %s", opp.pair_id)
            return

        # Validation des risques
        ok, reason = validate_trade(
            pair=pair,
            capital_needed=self._capital_per_trade,
            portfolio=self.portfolio,
            trades=self.trades,
            max_positions=self._max_positions,
            min_time=self._min_time,
            min_liquidity=self._min_liquidity,
        )
        if not ok:
            logger.info("Trade refused for %s %s: %s", pair.asset, pair.timeframe, reason)
            return

        # Executer le paper trade (arb simultane : les deux legs en meme temps)
        await self._execute_simultaneous_arb(pair, opp)

    async def _execute_simultaneous_arb(self, pair: MarketPair, opp: Opportunity) -> None:
        """Execute un arb simultane : achete les deux legs immediatement."""
        capital = self._capital_per_trade
        p1 = opp.leg1_price
        p2 = opp.leg2_price

        result = arbitrage_profit(p1, p2, capital)
        if not result["is_profitable"]:
            logger.info("Arb no longer profitable after recalculation")
            return

        # Calculer les shares reelles apres fees
        stake1 = result["stake_leg1"]
        stake2 = result["stake_leg2"]
        shares1 = shares_after_fee(stake1, p1)
        shares2 = shares_after_fee(stake2, p2)

        now = datetime.now(timezone.utc)
        trade_id = str(uuid.uuid4())[:8]
        leg1_side = opp.leg1_side
        leg2_side = Side.DOWN if leg1_side == Side.UP else Side.UP

        trade = PaperTrade(
            id=trade_id,
            pair_id=pair.pair_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            leg1_side=leg1_side,
            leg1_price=p1,
            leg1_shares=shares1,
            leg1_fee=result["fee_leg1"],
            leg1_timestamp=now,
            leg1_stake=stake1,
            leg2_side=leg2_side,
            leg2_price=p2,
            leg2_shares=shares2,
            leg2_fee=result["fee_leg2"],
            leg2_timestamp=now,
            leg2_stake=stake2,
            status=TradeStatus.FULLY_HEDGED,
            capital_deployed=capital,
            total_fees=result["total_fees"],
            resolution_time=pair.resolution_time,
        )

        # Mettre a jour le portfolio
        self.trades[trade_id] = trade
        self.portfolio.current_capital -= capital
        self.portfolio.total_deployed += capital
        self.portfolio.total_fees_paid += result["total_fees"]
        self.portfolio.total_trades += 1
        self.portfolio.active_positions.append(trade_id)

        logger.info(
            "TRADE EXECUTED: %s | %s %s | p1=%.3f p2=%.3f | Capital=$%.2f | Est. ROI=%.2f%%",
            trade_id,
            pair.asset,
            pair.timeframe,
            p1,
            p2,
            capital,
            result["worst_case_roi"],
        )

        await self._event_bus.publish(Event(
            type="trade_opened",
            data=trade.to_dict(),
        ))

    async def _check_resolutions(self) -> None:
        """Verifie si des trades hedges ont atteint leur resolution_time."""
        now = datetime.now(timezone.utc)
        resolved_ids: list[str] = []

        for trade_id in list(self.portfolio.active_positions):
            trade = self.trades.get(trade_id)
            if not trade or trade.status != TradeStatus.FULLY_HEDGED:
                continue
            if not trade.resolution_time:
                continue
            if now < trade.resolution_time:
                continue

            # Resoudre le trade
            # Pour un arb fully hedged, le payout est le min des deux legs de shares
            min_shares = min(trade.leg1_shares, trade.leg2_shares or 0)
            payout = min_shares * 1.0  # 1 USDC par share gagnante

            profit = payout - trade.capital_deployed
            roi = (profit / trade.capital_deployed * 100) if trade.capital_deployed > 0 else 0

            trade.payout = round(payout, 4)
            trade.profit = round(profit, 4)
            trade.roi = round(roi, 4)
            trade.resolved_at = now
            trade.resolution_outcome = "hedged"

            if profit >= 0:
                trade.status = TradeStatus.RESOLVED_WIN
                self.portfolio.winning_trades += 1
            else:
                trade.status = TradeStatus.RESOLVED_LOSS
                self.portfolio.losing_trades += 1

            self.portfolio.current_capital += payout
            self.portfolio.total_deployed -= trade.capital_deployed
            self.portfolio.total_pnl += profit
            resolved_ids.append(trade_id)

            logger.info(
                "TRADE RESOLVED: %s | %s %s | Profit=$%.4f (%.2f%%) | Status=%s",
                trade_id,
                trade.asset,
                trade.timeframe,
                profit,
                roi,
                trade.status.value,
            )

            await self._event_bus.publish(Event(
                type="trade_resolved",
                data=trade.to_dict(),
            ))

        for tid in resolved_ids:
            if tid in self.portfolio.active_positions:
                self.portfolio.active_positions.remove(tid)

        if resolved_ids:
            await self._event_bus.publish(Event(
                type="portfolio_update",
                data=self.portfolio.to_dict(),
            ))

    def _find_pair(self, pair_id: str) -> Optional[MarketPair]:
        for pair in self._pairs_ref:
            if pair.pair_id == pair_id:
                return pair
        return None
