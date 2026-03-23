"""
Paper execution engine.

Deux modes d'execution :
1. LEG 1 : acheter un cote quand il passe sous 0.50
2. LEG 2 : completer l'arb quand l'autre cote passe aussi sous 0.50

Gere aussi la resolution des marches (payout).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.fees import calculate_fee, shares_after_fee
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
        self._running = True
        queue = await self._event_bus.subscribe()
        logger.info("PaperExecutor started (capital: $%.2f)", self.portfolio.current_capital)

        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                if event.type == "opportunity_detected":
                    await self._handle_leg1(event)
                elif event.type == "leg2_opportunity":
                    await self._handle_leg2(event)
                elif event.type == "price_update":
                    await self._check_resolutions()
            except asyncio.TimeoutError:
                await self._check_resolutions()
            except Exception as e:
                logger.error("Executor error: %s", e, exc_info=True)

    def stop(self) -> None:
        self._running = False

    async def _handle_leg1(self, event: Event) -> None:
        """Acheter la leg 1 (un seul cote)."""
        opp = Opportunity.from_dict(event.data)

        pair = self._find_pair(opp.pair_id)
        if not pair:
            return

        # Validation risques
        # On deploie la moitie du capital par trade pour la leg 1
        leg1_capital = self._capital_per_trade / 2

        ok, reason = validate_trade(
            pair=pair,
            capital_needed=leg1_capital,
            portfolio=self.portfolio,
            trades=self.trades,
            max_positions=self._max_positions,
            min_time=self._min_time,
            min_liquidity=self._min_liquidity,
        )
        if not ok:
            logger.info("Leg1 refused %s %s: %s", pair.asset, pair.timeframe, reason)
            return

        # Executer leg 1
        price = opp.leg1_price
        shares = shares_after_fee(leg1_capital, price)
        fee = calculate_fee(leg1_capital / price, price)

        now = datetime.now(timezone.utc)
        trade_id = str(uuid.uuid4())[:8]

        trade = PaperTrade(
            id=trade_id,
            pair_id=pair.pair_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            leg1_side=opp.leg1_side,
            leg1_price=price,
            leg1_shares=shares,
            leg1_fee=fee,
            leg1_timestamp=now,
            leg1_stake=leg1_capital,
            status=TradeStatus.LEG1_OPEN,
            capital_deployed=leg1_capital,
            total_fees=fee,
            resolution_time=pair.resolution_time,
        )

        self.trades[trade_id] = trade
        self.portfolio.current_capital -= leg1_capital
        self.portfolio.total_deployed += leg1_capital
        self.portfolio.total_fees_paid += fee
        self.portfolio.total_trades += 1
        self.portfolio.active_positions.append(trade_id)

        logger.info(
            "LEG1 EXECUTED: %s | %s %s | %s=%.3f | Capital=$%.2f | Shares=%.2f",
            trade_id,
            pair.asset,
            pair.timeframe,
            opp.leg1_side.value,
            price,
            leg1_capital,
            shares,
        )

        await self._event_bus.publish(Event(
            type="trade_opened",
            data=trade.to_dict(),
        ))

    async def _handle_leg2(self, event: Event) -> None:
        """Completer la leg 2 pour verrouiller l'arb."""
        data = event.data
        trade_id = data["trade_id"]
        leg2_price = data["leg2_price"]
        leg2_side = Side(data["leg2_side"])

        trade = self.trades.get(trade_id)
        if not trade or trade.status != TradeStatus.LEG1_OPEN:
            return

        # Capital pour leg 2 = meme montant que leg 1
        leg2_capital = trade.leg1_stake
        if self.portfolio.current_capital < leg2_capital:
            logger.warning("Pas assez de capital pour leg 2 (%s)", trade_id)
            return

        shares = shares_after_fee(leg2_capital, leg2_price)
        fee = calculate_fee(leg2_capital / leg2_price, leg2_price)
        now = datetime.now(timezone.utc)

        # Completer le trade
        trade.leg2_side = leg2_side
        trade.leg2_price = leg2_price
        trade.leg2_shares = shares
        trade.leg2_fee = fee
        trade.leg2_timestamp = now
        trade.leg2_stake = leg2_capital
        trade.status = TradeStatus.FULLY_HEDGED
        trade.capital_deployed += leg2_capital
        trade.total_fees += fee

        self.portfolio.current_capital -= leg2_capital
        self.portfolio.total_deployed += leg2_capital
        self.portfolio.total_fees_paid += fee

        combined = trade.leg1_price + leg2_price

        logger.info(
            "LEG2 COMPLETED: %s | %s %s | %s=%.3f | Combined=%.4f | Capital total=$%.2f",
            trade_id,
            trade.asset,
            trade.timeframe,
            leg2_side.value,
            leg2_price,
            combined,
            trade.capital_deployed,
        )

        await self._event_bus.publish(Event(
            type="trade_completed",
            data=trade.to_dict(),
        ))

    async def _check_resolutions(self) -> None:
        """Verifie les trades qui ont atteint leur resolution_time."""
        now = datetime.now(timezone.utc)
        resolved_ids: list[str] = []

        for trade_id in list(self.portfolio.active_positions):
            trade = self.trades.get(trade_id)
            if not trade:
                continue
            if not trade.resolution_time or now < trade.resolution_time:
                continue

            if trade.status == TradeStatus.FULLY_HEDGED:
                # Arb complet → payout garanti
                min_shares = min(trade.leg1_shares, trade.leg2_shares or 0)
                payout = min_shares * 1.0
            elif trade.status == TradeStatus.LEG1_OPEN:
                # Leg 1 seule → on a parie sur un seul cote
                # 50/50 chance : soit on gagne (payout = shares), soit on perd (payout = 0)
                # Pour le paper trading, on simule le resultat
                # On utilise le prix comme proxy de probabilite
                import random
                won = random.random() < trade.leg1_price  # prix = proba implicite
                payout = trade.leg1_shares * 1.0 if won else 0.0
            else:
                continue

            profit = payout - trade.capital_deployed
            roi = (profit / trade.capital_deployed * 100) if trade.capital_deployed > 0 else 0

            trade.payout = round(payout, 4)
            trade.profit = round(profit, 4)
            trade.roi = round(roi, 4)
            trade.resolved_at = now

            if profit >= 0:
                trade.status = TradeStatus.RESOLVED_WIN
                trade.resolution_outcome = "win"
                self.portfolio.winning_trades += 1
            else:
                trade.status = TradeStatus.RESOLVED_LOSS
                trade.resolution_outcome = "loss"
                self.portfolio.losing_trades += 1

            self.portfolio.current_capital += payout
            self.portfolio.total_deployed -= trade.capital_deployed
            self.portfolio.total_pnl += profit
            resolved_ids.append(trade_id)

            logger.info(
                "RESOLVED: %s | %s %s | %s | Payout=$%.4f Profit=$%.4f (%.2f%%)",
                trade_id,
                trade.asset,
                trade.timeframe,
                trade.status.value,
                payout,
                profit,
                roi,
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
