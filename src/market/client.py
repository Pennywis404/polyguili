"""
Client async pour l'API CLOB de Polymarket.
Gestion des erreurs avec retry backoff + rate limiting via semaphore.
"""
import asyncio
import logging
import ssl
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_MIN = 2
BACKOFF_MAX = 10
CONCURRENT_LIMIT = 5


class PolymarketClient:
    def __init__(self, base_url: str = "https://clob.polymarket.com") -> None:
        self._base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)

    async def __aenter__(self) -> "PolymarketClient":
        # Disable SSL verification for macOS dev environment
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

    async def _request(self, method: str, path: str, params: Optional[dict] = None) -> Any:
        if not self._session:
            raise RuntimeError("Client not initialized. Use 'async with PolymarketClient() as client:'")

        url = f"{self._base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            async with self._semaphore:
                try:
                    async with self._session.request(method, url, params=params) as resp:
                        if resp.status == 429:
                            wait = BACKOFF_MIN * (2 ** (attempt - 1))
                            logger.warning("Rate limited, waiting %ds (attempt %d/%d)", wait, attempt, MAX_RETRIES)
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        return await resp.json()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_error = e
                    if attempt < MAX_RETRIES:
                        wait = min(BACKOFF_MIN * (2 ** (attempt - 1)), BACKOFF_MAX)
                        logger.warning("Request failed (%s), retrying in %ds (%d/%d)", e, wait, attempt, MAX_RETRIES)
                        await asyncio.sleep(wait)

        logger.error("Request failed after %d attempts: %s %s", MAX_RETRIES, method, url)
        raise last_error or RuntimeError(f"Request failed: {method} {url}")

    async def get_markets(self, next_cursor: str = "") -> dict:
        """Fetch les marches actifs. Retourne {"data": [...], "next_cursor": "..."}."""
        params: dict[str, str] = {}
        if next_cursor:
            params["next_cursor"] = next_cursor
        return await self._request("GET", "/markets", params=params)

    async def get_all_markets(self) -> list[dict]:
        """Fetch tous les marches avec pagination."""
        all_markets: list[dict] = []
        cursor = ""
        while True:
            result = await self.get_markets(next_cursor=cursor)
            data = result.get("data", result) if isinstance(result, dict) else result
            if isinstance(data, list):
                all_markets.extend(data)
            elif isinstance(data, dict) and "data" in data:
                all_markets.extend(data["data"])
            cursor = result.get("next_cursor", "") if isinstance(result, dict) else ""
            if not cursor or cursor == "LTE=":
                break
        return all_markets

    async def get_orderbook(self, token_id: str) -> dict:
        """Fetch l'orderbook pour un token_id."""
        return await self._request("GET", "/book", params={"token_id": token_id})

    async def get_price(self, token_id: str) -> dict:
        """Fetch le prix simplifie (midpoint)."""
        return await self._request("GET", "/price", params={"token_id": token_id})

    async def get_market(self, condition_id: str) -> dict:
        """Fetch un marche specifique par condition_id."""
        return await self._request("GET", f"/markets/{condition_id}")
