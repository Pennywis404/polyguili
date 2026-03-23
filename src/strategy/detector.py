"""
Detection d'opportunites d'arbitrage temporel.

Strategie :
1. Quand Up < 0.45 → signal d'achat leg 1 (Up)
2. Quand Down < 0.45 → signal d'achat leg 1 (Down)
3. Si on a deja une leg 1 ouverte sur cette paire et que l'autre cote < 0.45
   → signal de completion leg 2
4. On ne rentre PAS apres 3 minutes (< 2 min restantes avant resolution)

Le but : capturer chaque cote quand il passe sous 0.45.
Combined < 0.90 = profit garanti ~10%+ au payout.
"""
import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.fees import arbitrage_profit
from src.core.models import MarketPair, Opportunity, PaperTrade, Side, TradeStatus

logger = logging.getLogger(__name__)

ENTRY_THRESHOLD = 0.45  # Acheter un cote des qu'il passe sous ce seuil


class OpportunityDetector:
    def __init__(
        self,
        event_bus: EventBus,
        pairs_ref: list[MarketPair],
        trades: dict[str, PaperTrade],
        portfolio_active_positions: list[str],
        capital_per_trade: float = 100.0,
        min_time_to_resolution: int = 120,
        min_liquidity: float = 50.0,
    ) -> None:
        self._event_bus = event_bus
        self._pairs_ref = pairs_ref
        self._trades = trades
        self._active_positions = portfolio_active_positions
        self._capital_per_trade = capital_per_trade
        self._min_time_to_resolution = min_time_to_resolution
        self._min_liquidity = min_liquidity
        self._running = False

        # Cooldown par pair_id pour eviter le spam
        self._last_signal: dict[str, datetime] = {}

    async def run(self) -> None:
        self._running = True
        queue = await self._event_bus.subscribe()
        logger.info("OpportunityDetector started (entry threshold: %.2f)", ENTRY_THRESHOLD)

        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                if event.type == "price_update":
                    await self._process_price_update(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Detector error: %s", e, exc_info=True)

    def stop(self) -> None:
        self._running = False

    async def _process_price_update(self, event: Event) -> None:
        data = event.data
        pair_id = data["pair_id"]
        best_ask_up = data["best_ask_up"]
        best_ask_down = data["best_ask_down"]
        ask_size_up = data.get("ask_size_up", 0)
        ask_size_down = data.get("ask_size_down", 0)

        pair = self._find_pair(pair_id)
        if not pair:
            return

        # Verifier temps restant
        remaining = (pair.resolution_time - datetime.now(timezone.utc)).total_seconds()
        if remaining < self._min_time_to_resolution:
            return

        # Chercher si on a deja une leg 1 ouverte sur cette paire
        open_trade = self._find_open_leg1(pair_id)

        if open_trade:
            # On a une leg 1 → chercher a completer la leg 2
            await self._check_leg2(open_trade, pair, best_ask_up, best_ask_down, ask_size_up, ask_size_down)
        else:
            # Pas de position ouverte → chercher une leg 1
            await self._check_leg1(pair, best_ask_up, best_ask_down, ask_size_up, ask_size_down)

    async def _check_leg1(
        self,
        pair: MarketPair,
        best_ask_up: float,
        best_ask_down: float,
        ask_size_up: float,
        ask_size_down: float,
    ) -> None:
        """Detecter si un cote passe sous le seuil → ouvrir leg 1."""
        # Cooldown 10s par paire
        now = datetime.now(timezone.utc)
        last = self._last_signal.get(pair.pair_id)
        if last and (now - last).total_seconds() < 10:
            return

        leg1_side: Optional[Side] = None
        leg1_price = 0.0
        leg2_price_estimate = 0.0
        liquidity = 0.0

        if best_ask_up > 0 and best_ask_up < ENTRY_THRESHOLD and ask_size_up >= self._min_liquidity:
            leg1_side = Side.UP
            leg1_price = best_ask_up
            leg2_price_estimate = best_ask_down
            liquidity = ask_size_up
        elif best_ask_down > 0 and best_ask_down < ENTRY_THRESHOLD and ask_size_down >= self._min_liquidity:
            leg1_side = Side.DOWN
            leg1_price = best_ask_down
            leg2_price_estimate = best_ask_up
            liquidity = ask_size_down

        if not leg1_side:
            return

        combined_estimate = leg1_price + leg2_price_estimate
        result = arbitrage_profit(leg1_price, leg2_price_estimate, self._capital_per_trade)

        self._last_signal[pair.pair_id] = now

        logger.info(
            "LEG1 SIGNAL: %s %s | %s=%.3f (< %.2f) | Combined est.=%.4f | ROI est.=%.2f%%",
            pair.asset,
            pair.timeframe,
            leg1_side.value,
            leg1_price,
            ENTRY_THRESHOLD,
            combined_estimate,
            result["worst_case_roi"],
        )

        opp = Opportunity(
            id=str(uuid.uuid4())[:8],
            pair_id=pair.pair_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            leg1_side=leg1_side,
            leg1_price=leg1_price,
            leg2_price=leg2_price_estimate,
            timestamp=now,
            combined_cost=combined_estimate,
            estimated_profit_pct=result["worst_case_roi"],
            available_liquidity=liquidity,
            status="leg1_signal",
        )

        await self._event_bus.publish(Event(
            type="opportunity_detected",
            data=opp.to_dict(),
        ))

    async def _check_leg2(
        self,
        open_trade: PaperTrade,
        pair: MarketPair,
        best_ask_up: float,
        best_ask_down: float,
        ask_size_up: float,
        ask_size_down: float,
    ) -> None:
        """On a une leg 1 ouverte → chercher a completer avec l'autre cote sous le seuil."""
        # L'autre cote doit passer sous le seuil
        if open_trade.leg1_side == Side.UP:
            # On a achete Up, on attend que Down < seuil
            if best_ask_down > 0 and best_ask_down < ENTRY_THRESHOLD and ask_size_down >= self._min_liquidity:
                combined = open_trade.leg1_price + best_ask_down
                if combined < 1.0:
                    logger.info(
                        "LEG2 SIGNAL: %s %s | Down=%.3f | Combined=%.4f (< 1.00) → COMPLETE ARB",
                        pair.asset,
                        pair.timeframe,
                        best_ask_down,
                        combined,
                    )
                    await self._event_bus.publish(Event(
                        type="leg2_opportunity",
                        data={
                            "trade_id": open_trade.id,
                            "pair_id": pair.pair_id,
                            "leg2_side": Side.DOWN.value,
                            "leg2_price": best_ask_down,
                            "combined_cost": combined,
                        },
                    ))
        else:
            # On a achete Down, on attend que Up < seuil
            if best_ask_up > 0 and best_ask_up < ENTRY_THRESHOLD and ask_size_up >= self._min_liquidity:
                combined = best_ask_up + open_trade.leg1_price
                if combined < 1.0:
                    logger.info(
                        "LEG2 SIGNAL: %s %s | Up=%.3f | Combined=%.4f (< 1.00) → COMPLETE ARB",
                        pair.asset,
                        pair.timeframe,
                        best_ask_up,
                        combined,
                    )
                    await self._event_bus.publish(Event(
                        type="leg2_opportunity",
                        data={
                            "trade_id": open_trade.id,
                            "pair_id": pair.pair_id,
                            "leg2_side": Side.UP.value,
                            "leg2_price": best_ask_up,
                            "combined_cost": combined,
                        },
                    ))

    def _find_pair(self, pair_id: str) -> Optional[MarketPair]:
        for pair in self._pairs_ref:
            if pair.pair_id == pair_id:
                return pair
        return None

    def _find_open_leg1(self, pair_id: str) -> Optional[PaperTrade]:
        """Cherche un trade LEG1_OPEN sur cette paire."""
        for tid in self._active_positions:
            trade = self._trades.get(tid)
            if trade and trade.pair_id == pair_id and trade.status == TradeStatus.LEG1_OPEN:
                return trade
        return None
