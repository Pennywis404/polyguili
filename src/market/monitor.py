"""
Boucle de monitoring des marches crypto Up/Down Polymarket.
Refresh les paires (5min/15min) periodiquement et poll les prix via CLOB.
"""
import asyncio
import logging
from datetime import datetime, timezone

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
        self._running = True
        logger.info("MarketMonitor starting (poll=%ds, refresh=%ds)", self._poll_interval, self._pair_refresh_interval)

        await self._refresh_pairs()
        last_refresh = asyncio.get_event_loop().time()

        while self._running:
            try:
                now = asyncio.get_event_loop().time()
                if now - last_refresh >= self._pair_refresh_interval:
                    await self._refresh_pairs()
                    last_refresh = now

                # Retirer les paires qui ont deja resolve
                self._prune_expired_pairs()

                await self._poll_prices()
            except Exception as e:
                logger.error("Monitor error: %s", e, exc_info=True)

            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    def _prune_expired_pairs(self) -> None:
        """Retire les paires dont la resolution est passee."""
        now = datetime.now(timezone.utc)
        before = len(self.active_pairs)
        self.active_pairs = [p for p in self.active_pairs if p.resolution_time > now]
        pruned = before - len(self.active_pairs)
        if pruned > 0:
            logger.info("Pruned %d expired pairs, %d remaining", pruned, len(self.active_pairs))

    async def _refresh_pairs(self) -> None:
        """Fetch les marches crypto Up/Down actifs via Gamma API."""
        try:
            markets = await self._client.get_crypto_updown_markets(lookahead_minutes=30)
            new_pairs = self._pair_manager.build_pairs_from_markets(markets)

            # Merge: ajouter les nouvelles, garder les existantes si encore actives
            existing_ids = {p.pair_id for p in self.active_pairs}
            for pair in new_pairs:
                if pair.pair_id not in existing_ids:
                    self.active_pairs.append(pair)

            logger.info("Refreshed: %d active pairs total", len(self.active_pairs))
        except Exception as e:
            logger.error("Failed to refresh pairs: %s", e)

    async def _poll_prices(self) -> None:
        """Poll les orderbooks de toutes les paires actives."""
        if not self.active_pairs:
            return

        batch_size = 5
        updated_pairs: list[MarketPair] = []

        for i in range(0, len(self.active_pairs), batch_size):
            batch = self.active_pairs[i:i + batch_size]
            tasks = [self._update_pair_prices(pair) for pair in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(results):
                if isinstance(result, MarketPair):
                    updated_pairs.append(result)
                elif isinstance(result, Exception):
                    updated_pairs.append(batch[j])
                    logger.debug("Failed to update %s %s: %s", batch[j].asset, batch[j].timeframe, result)

        self.active_pairs = updated_pairs

    async def _update_pair_prices(self, pair: MarketPair) -> MarketPair:
        """Fetch les orderbooks Up et Down et met a jour les prix."""
        book_up, book_down = await asyncio.gather(
            self._client.get_orderbook(pair.token_id_up),
            self._client.get_orderbook(pair.token_id_down),
        )

        updated = PairManager.update_prices(pair, book_up, book_down)
        combined = updated.best_ask_up + updated.best_ask_down

        if combined > 0 and combined < 1.05:
            logger.info(
                "%s %s | Up: %.3f Down: %.3f | Combined: %.4f | Spread vs 1.00: %+.4f",
                updated.asset,
                updated.timeframe,
                updated.best_ask_up,
                updated.best_ask_down,
                combined,
                1.0 - combined,
            )

        await self._event_bus.publish(Event(
            type="price_update",
            data={
                "pair_id": updated.pair_id,
                "asset": updated.asset,
                "timeframe": updated.timeframe,
                "price_up": updated.price_up,
                "price_down": updated.price_down,
                "best_ask_up": updated.best_ask_up,
                "best_ask_down": updated.best_ask_down,
                "ask_size_up": updated.ask_size_up,
                "ask_size_down": updated.ask_size_down,
                "combined_cost": combined,
                "resolution_time": updated.resolution_time.isoformat(),
            },
        ))

        return updated
