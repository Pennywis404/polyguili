"""
Detection d'opportunites d'arbitrage temporel.
Ecoute les events price_update et identifie les fenetres d'arb.
"""
import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.fees import arbitrage_profit
from src.core.models import MarketPair, Opportunity, Side

logger = logging.getLogger(__name__)

# Taille du buffer de prix par paire (pour l'arb temporel)
PRICE_BUFFER_SIZE = 60


class OpportunityDetector:
    def __init__(
        self,
        event_bus: EventBus,
        pairs_ref: list[MarketPair],
        simultaneous_threshold: float = 0.98,
        combined_cost_target: float = 0.97,
        leg1_max_price: float = 0.52,
        capital_per_trade: float = 100.0,
        min_time_to_resolution: int = 120,
        min_liquidity: float = 50.0,
    ) -> None:
        self._event_bus = event_bus
        self._pairs_ref = pairs_ref
        self._simultaneous_threshold = simultaneous_threshold
        self._combined_cost_target = combined_cost_target
        self._leg1_max_price = leg1_max_price
        self._capital_per_trade = capital_per_trade
        self._min_time_to_resolution = min_time_to_resolution
        self._min_liquidity = min_liquidity
        self._running = False

        # Rolling buffer de prix par pair_id: deque of (timestamp, best_ask_up, best_ask_down)
        self._price_buffers: dict[str, deque] = {}

        # Opportunites recentes (eviter les doublons)
        self._recent_opps: dict[str, datetime] = {}

    async def run(self) -> None:
        """Boucle principale : ecoute les events price_update."""
        self._running = True
        queue = await self._event_bus.subscribe()
        logger.info("OpportunityDetector started")

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
        combined = data["combined_cost"]

        # Mettre a jour le buffer de prix
        if pair_id not in self._price_buffers:
            self._price_buffers[pair_id] = deque(maxlen=PRICE_BUFFER_SIZE)
        self._price_buffers[pair_id].append((datetime.now(timezone.utc), best_ask_up, best_ask_down))

        # Trouver la paire correspondante
        pair = self._find_pair(pair_id)
        if not pair:
            return

        # Verifier le temps restant
        remaining = (pair.resolution_time - datetime.now(timezone.utc)).total_seconds()
        if remaining < self._min_time_to_resolution:
            return

        # Verifier la liquidite
        if data.get("ask_size_up", 0) < self._min_liquidity or data.get("ask_size_down", 0) < self._min_liquidity:
            return

        # Detection arb simultane
        if combined < self._simultaneous_threshold and best_ask_up > 0 and best_ask_down > 0:
            result = arbitrage_profit(best_ask_up, best_ask_down, self._capital_per_trade)
            if result["is_profitable"]:
                await self._emit_opportunity(
                    pair=pair,
                    leg1_side=Side.UP if best_ask_up <= best_ask_down else Side.DOWN,
                    leg1_price=min(best_ask_up, best_ask_down),
                    leg2_price=max(best_ask_up, best_ask_down),
                    combined_cost=combined,
                    roi=result["worst_case_roi"],
                    liquidity=min(data.get("ask_size_up", 0), data.get("ask_size_down", 0)),
                )

    def _find_pair(self, pair_id: str) -> Optional[MarketPair]:
        for pair in self._pairs_ref:
            if pair.pair_id == pair_id:
                return pair
        return None

    async def _emit_opportunity(
        self,
        pair: MarketPair,
        leg1_side: Side,
        leg1_price: float,
        leg2_price: float,
        combined_cost: float,
        roi: float,
        liquidity: float,
    ) -> None:
        # Eviter les doublons (1 opp par paire par 30 secondes)
        now = datetime.now(timezone.utc)
        last = self._recent_opps.get(pair.pair_id)
        if last and (now - last).total_seconds() < 30:
            return

        opp_id = str(uuid.uuid4())[:8]
        opp = Opportunity(
            id=opp_id,
            pair_id=pair.pair_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            leg1_side=leg1_side,
            leg1_price=leg1_price,
            leg2_price=leg2_price,
            timestamp=now,
            combined_cost=combined_cost,
            estimated_profit_pct=roi,
            available_liquidity=liquidity,
        )

        self._recent_opps[pair.pair_id] = now

        logger.info(
            "OPPORTUNITY DETECTED: %s %s | Combined: %.4f | ROI: %.2f%% | Liquidity: $%.0f",
            pair.asset,
            pair.timeframe,
            combined_cost,
            roi,
            liquidity,
        )

        await self._event_bus.publish(Event(
            type="opportunity_detected",
            data=opp.to_dict(),
        ))
