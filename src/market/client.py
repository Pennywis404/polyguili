"""
Client async pour les APIs Polymarket (Gamma + CLOB).
Gestion des erreurs avec retry backoff + rate limiting via semaphore.
"""
import asyncio
import logging
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_MIN = 2
BACKOFF_MAX = 10
CONCURRENT_LIMIT = 5


class PolymarketClient:
    def __init__(
        self,
        clob_url: str = "https://clob.polymarket.com",
        gamma_url: str = "https://gamma-api.polymarket.com",
    ) -> None:
        self._clob_url = clob_url.rstrip("/")
        self._gamma_url = gamma_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)

    async def __aenter__(self) -> "PolymarketClient":
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            connector=connector,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _request(self, url: str, params: Optional[dict] = None) -> Any:
        if not self._session:
            raise RuntimeError("Client not initialized. Use 'async with'")

        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            async with self._semaphore:
                try:
                    async with self._session.get(url, params=params) as resp:
                        if resp.status == 429:
                            wait = BACKOFF_MIN * (2 ** (attempt - 1))
                            logger.warning("Rate limited, waiting %ds (%d/%d)", wait, attempt, MAX_RETRIES)
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        return await resp.json()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_error = e
                    if attempt < MAX_RETRIES:
                        wait = min(BACKOFF_MIN * (2 ** (attempt - 1)), BACKOFF_MAX)
                        logger.warning("Request failed (%s), retry in %ds (%d/%d)", e, wait, attempt, MAX_RETRIES)
                        await asyncio.sleep(wait)

        logger.error("Request failed after %d attempts: %s", MAX_RETRIES, url)
        raise last_error or RuntimeError(f"Request failed: {url}")

    # --- Gamma API ---

    async def get_crypto_updown_markets(self, lookahead_minutes: int = 30) -> list[dict]:
        """
        Fetch les marches crypto Up/Down actifs (5min et 15min).
        Utilise end_date_min/max pour trouver ceux qui resolvent bientot.
        """
        now = datetime.now(timezone.utc)
        soon = now + timedelta(minutes=lookahead_minutes)

        return await self._request(
            f"{self._gamma_url}/markets",
            params={
                "active": "true",
                "closed": "false",
                "end_date_min": now.isoformat(),
                "end_date_max": soon.isoformat(),
                "limit": "50",
            },
        )

    async def get_event_by_slug(self, slug: str) -> list[dict]:
        """Fetch un event par son slug."""
        return await self._request(
            f"{self._gamma_url}/events",
            params={"slug": slug},
        )

    # --- CLOB API ---

    async def get_orderbook(self, token_id: str) -> dict:
        """Fetch l'orderbook pour un token_id."""
        return await self._request(f"{self._clob_url}/book", params={"token_id": token_id})

    async def get_price(self, token_id: str) -> dict:
        """Fetch le prix simplifie."""
        return await self._request(f"{self._clob_url}/price", params={"token_id": token_id})
