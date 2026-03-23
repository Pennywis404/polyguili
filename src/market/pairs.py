"""
Detection des paires crypto Up/Down sur Polymarket.
Les marches 5min/15min se creent dynamiquement avec le slug pattern:
  {asset}-updown-{5m|15m}-{unix_timestamp}

Chaque marche a deux outcomes: "Up" et "Down" avec des clobTokenIds.
Pour l'arb temporel: on achete Up + Down si combined < 1.00.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from src.core.models import MarketPair

logger = logging.getLogger(__name__)

# Pattern pour extraire asset et timeframe du slug
SLUG_PATTERN = re.compile(r"^(\w+)-updown-(5m|15m)-(\d+)$")

ASSET_MAP: dict[str, str] = {
    "btc": "BTC",
    "eth": "ETH",
    "sol": "SOL",
    "xrp": "XRP",
    "doge": "DOGE",
    "bnb": "BNB",
    "hype": "HYPE",
}


class PairManager:
    def __init__(
        self,
        target_assets: tuple[str, ...] = ("BTC",),
        target_timeframes: tuple[str, ...] = ("5min",),
    ) -> None:
        self._target_assets = set(target_assets)
        self._target_timeframes = set(target_timeframes)

    def build_pairs_from_markets(self, markets: list[dict]) -> list[MarketPair]:
        """
        Construit des MarketPair a partir des marches Gamma API.
        Filtre uniquement les marches crypto Up/Down correspondant aux assets cibles.
        """
        pairs: list[MarketPair] = []

        for market in markets:
            slug = market.get("slug", "")
            match = SLUG_PATTERN.match(slug)
            if not match:
                continue

            asset_key, timeframe_key, timestamp_str = match.groups()
            asset = ASSET_MAP.get(asset_key)
            if not asset or asset not in self._target_assets:
                continue

            timeframe = "5min" if timeframe_key == "5m" else "15min"
            if timeframe not in self._target_timeframes:
                continue

            pair = self._build_pair(market, asset, timeframe)
            if pair:
                pairs.append(pair)

        logger.info(
            "Found %d crypto Up/Down pairs: %s",
            len(pairs),
            [(p.asset, p.timeframe) for p in pairs],
        )
        return pairs

    def _build_pair(self, market: dict, asset: str, timeframe: str) -> Optional[MarketPair]:
        """Construit un MarketPair a partir d'un marche Gamma crypto Up/Down."""
        try:
            outcomes_raw = market.get("outcomes", "[]")
            clob_ids_raw = market.get("clobTokenIds", "[]")
            prices_raw = market.get("outcomePrices", "[]")

            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

            if len(outcomes) != 2 or len(clob_ids) != 2:
                return None

            # Identifier Up et Down
            up_idx = None
            down_idx = None
            for i, outcome in enumerate(outcomes):
                if outcome.lower() == "up":
                    up_idx = i
                elif outcome.lower() == "down":
                    down_idx = i

            if up_idx is None or down_idx is None:
                return None

            token_id_up = clob_ids[up_idx]
            token_id_down = clob_ids[down_idx]
            price_up = float(prices[up_idx]) if prices else 0.0
            price_down = float(prices[down_idx]) if prices else 0.0

            end_date = market.get("endDate", market.get("end_date_iso", ""))
            if end_date:
                resolution_time = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            else:
                return None

            condition_id = market.get("conditionId", market.get("condition_id", ""))
            pair_id = f"{asset}_{timeframe}_{end_date}"

            return MarketPair(
                pair_id=pair_id,
                asset=asset,
                timeframe=timeframe,
                token_id_up=token_id_up,
                token_id_down=token_id_down,
                condition_id_up=condition_id,
                condition_id_down=condition_id,
                resolution_time=resolution_time,
                price_up=price_up,
                price_down=price_down,
            )
        except (KeyError, ValueError, IndexError, json.JSONDecodeError) as e:
            logger.debug("Failed to build pair from %s: %s", market.get("slug", "?"), e)
            return None

    @staticmethod
    def update_prices(pair: MarketPair, book_up: dict, book_down: dict) -> MarketPair:
        """Retourne une nouvelle MarketPair avec les prix mis a jour depuis les orderbooks."""
        best_ask_up = _extract_best_ask(book_up)
        best_ask_down = _extract_best_ask(book_down)
        ask_size_up = _extract_ask_size(book_up)
        ask_size_down = _extract_ask_size(book_down)

        best_bid_up = _extract_best_bid(book_up)
        best_bid_down = _extract_best_bid(book_down)
        price_up = (best_ask_up + best_bid_up) / 2 if best_bid_up > 0 else best_ask_up
        price_down = (best_ask_down + best_bid_down) / 2 if best_bid_down > 0 else best_ask_down

        return MarketPair(
            pair_id=pair.pair_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            token_id_up=pair.token_id_up,
            token_id_down=pair.token_id_down,
            condition_id_up=pair.condition_id_up,
            condition_id_down=pair.condition_id_down,
            resolution_time=pair.resolution_time,
            price_up=price_up,
            price_down=price_down,
            best_ask_up=best_ask_up,
            best_ask_down=best_ask_down,
            ask_size_up=ask_size_up,
            ask_size_down=ask_size_down,
            last_update=datetime.now(timezone.utc),
        )


def _extract_best_ask(book: dict) -> float:
    """
    Best ask = prix le plus bas auquel on peut acheter.
    Sur Polymarket CLOB, les asks sont triees du plus cher au moins cher,
    donc le best ask est le DERNIER element de la liste.
    """
    asks = book.get("asks", [])
    if not asks:
        return 0.0
    return float(asks[-1].get("price", 0))


def _extract_best_bid(book: dict) -> float:
    """
    Best bid = prix le plus haut auquel on peut vendre.
    Les bids sont triees du moins cher au plus cher,
    donc le best bid est le DERNIER element.
    """
    bids = book.get("bids", [])
    if not bids:
        return 0.0
    return float(bids[-1].get("price", 0))


def _extract_ask_size(book: dict) -> float:
    asks = book.get("asks", [])
    if not asks:
        return 0.0
    return float(asks[-1].get("size", 0))
