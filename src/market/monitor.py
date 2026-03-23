"""
Boucle de monitoring des marches Polymarket.
Refresh les paires periodiquement et poll les prix en continu.
Publie des events price_update sur l'EventBus.
"""
import asyncio
import logging
from datetime import datetime

from src.core.events import Event, EventBus
from src.core.models import MarketPair
from src.market.client import PolymarketClient
from src.market.pairs import PairManager

logger = logging.getLogger(__name__)


class MarketMonitor:
    def __init__(
        self,
        client: PolymarketClient,
        pair_manager: PairManager,
        event_bus: EventBus,
        poll_interval: int = 3,
        pair_refresh_interval: int = 60,
    ) -> None:
        self._client = client
        self._pair_manager = pair_manager
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._pair_refresh_interval = pair_refresh_interval
        self.active_pairs: list[MarketPair] = []
        self._running = False

    async def run(self) -> None:
        """Boucle principale du monitor."""
        self._running = True
        logger.info("MarketMonitor starting (poll=%ds, refresh=%ds)", self._poll_interval, self._pair_refresh_interval)

        # Refresh initial des paires
        await self._refresh_pairs()

        last_refresh = asyncio.get_event_loop().time()

        while self._running:
            try:
                now = asyncio.get_event_loop().time()

                # Refresh des paires periodiquement
                if now - last_refresh >= self._pair_refresh_interval:
                    await self._refresh_pairs()
                    last_refresh = now

                # Poll les prix de toutes les paires actives
                await self._poll_prices()

            except Exception as e:
                logger.error("Monitor error: %s", e, exc_info=True)

            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    async def _refresh_pairs(self) -> None:
        """Refresh la liste des paires Up/Down actives."""
        try:
            markets = await self._client.get_all_markets()
            self.active_pairs = self._pair_manager.refresh_pairs(markets)
            logger.info("Refreshed pairs: %d active", len(self.active_pairs))
        except Exception as e:
            logger.error("Failed to refresh pairs: %s", e)

    async def _poll_prices(self) -> None:
        """Poll les prix de toutes les paires actives en parallele."""
        if not self.active_pairs:
            return

        tasks = [self._update_pair_prices(pair) for pair in self.active_pairs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        updated_pairs: list[MarketPair] = []
        for i, result in enumerate(results):
            if isinstance(result, MarketPair):
                updated_pairs.append(result)
            elif isinstance(result, Exception):
                logger.warning("Failed to update pair %s: %s", self.active_pairs[i].pair_id, result)

        self.active_pairs = updated_pairs

    async def _update_pair_prices(self, pair: MarketPair) -> MarketPair:
        """Fetch les orderbooks et met a jour les prix d'une paire."""
        book_up, book_down = await asyncio.gather(
            self._client.get_orderbook(pair.token_id_up),
            self._client.get_orderbook(pair.token_id_down),
        )

        updated_pair = PairManager.update_prices(pair, book_up, book_down)

        combined = updated_pair.best_ask_up + updated_pair.best_ask_down
        logger.debug(
            "%s %s | Up: %.2f Down: %.2f | Combined: %.4f",
            updated_pair.asset,
            updated_pair.timeframe,
            updated_pair.best_ask_up,
            updated_pair.best_ask_down,
            combined,
        )

        await self._event_bus.publish(Event(
            type="price_update",
            data={
                "pair_id": updated_pair.pair_id,
                "asset": updated_pair.asset,
                "timeframe": updated_pair.timeframe,
                "price_up": updated_pair.price_up,
                "price_down": updated_pair.price_down,
                "best_ask_up": updated_pair.best_ask_up,
                "best_ask_down": updated_pair.best_ask_down,
                "ask_size_up": updated_pair.ask_size_up,
                "ask_size_down": updated_pair.ask_size_down,
                "combined_cost": combined,
                "resolution_time": updated_pair.resolution_time.isoformat(),
            },
        ))

        return updated_pair
