"""
Detection et gestion des paires Up/Down pour les marches crypto Polymarket.
Groupe les marches par asset + timeframe pour former des paires tradables.
"""
import logging
import re
from datetime import datetime
from typing import Optional

from src.core.models import MarketPair

logger = logging.getLogger(__name__)

# Pattern pour identifier les marches crypto Up/Down
# Ex: "Will Bitcoin go up in the next 15 minutes?" ou "BTC 5-Minute Up"
CRYPTO_PATTERN = re.compile(
    r"(bitcoin|btc|ethereum|eth|solana|sol|xrp|ripple)",
    re.IGNORECASE,
)

DIRECTION_PATTERN = re.compile(r"\b(up|down)\b", re.IGNORECASE)

TIMEFRAME_PATTERN = re.compile(r"(\d+)\s*[-]?\s*min", re.IGNORECASE)

ASSET_MAP: dict[str, str] = {
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "eth": "ETH",
    "solana": "SOL",
    "sol": "SOL",
    "xrp": "XRP",
    "ripple": "XRP",
}


def _parse_asset(question: str) -> Optional[str]:
    match = CRYPTO_PATTERN.search(question)
    if not match:
        return None
    return ASSET_MAP.get(match.group(1).lower())


def _parse_direction(question: str) -> Optional[str]:
    match = DIRECTION_PATTERN.search(question)
    if not match:
        return None
    return match.group(1).lower()


def _parse_timeframe(question: str) -> Optional[str]:
    match = TIMEFRAME_PATTERN.search(question)
    if not match:
        return None
    minutes = match.group(1)
    return f"{minutes}min"


class PairManager:
    def __init__(self, target_assets: tuple[str, ...], target_timeframes: tuple[str, ...]) -> None:
        self._target_assets = set(target_assets)
        self._target_timeframes = set(target_timeframes)

    def refresh_pairs(self, markets: list[dict]) -> list[MarketPair]:
        """
        A partir des marches bruts de l'API, identifier et construire les paires Up/Down.
        Groupe par group_id d'abord, puis par parsing de la question en fallback.
        """
        # Grouper par group_id si disponible
        groups: dict[str, list[dict]] = {}
        ungrouped: list[dict] = []

        for market in markets:
            if not market.get("active", True) or market.get("closed", False):
                continue
            if not market.get("enable_order_book", market.get("enableOrderBook", True)):
                continue

            group_id = market.get("group_id")
            if group_id:
                groups.setdefault(group_id, []).append(market)
            else:
                ungrouped.append(market)

        pairs: list[MarketPair] = []

        # D'abord traiter les groupes
        for group_id, group_markets in groups.items():
            pair = self._try_build_pair_from_group(group_markets)
            if pair:
                pairs.append(pair)

        # Puis traiter les marches sans group_id par parsing
        pairs.extend(self._build_pairs_from_parsing(ungrouped))

        logger.info("Found %d active pairs: %s", len(pairs), [(p.asset, p.timeframe) for p in pairs])
        return pairs

    def _try_build_pair_from_group(self, group_markets: list[dict]) -> Optional[MarketPair]:
        """Essaie de construire une paire a partir d'un groupe de marches."""
        up_market: Optional[dict] = None
        down_market: Optional[dict] = None
        asset: Optional[str] = None
        timeframe: Optional[str] = None

        for market in group_markets:
            question = market.get("question", "")
            parsed_asset = _parse_asset(question)
            direction = _parse_direction(question)
            parsed_tf = _parse_timeframe(question)

            if parsed_asset:
                asset = parsed_asset
            if parsed_tf:
                timeframe = parsed_tf

            if direction == "up":
                up_market = market
            elif direction == "down":
                down_market = market

        if not (up_market and down_market and asset and timeframe):
            return None
        if asset not in self._target_assets or timeframe not in self._target_timeframes:
            return None

        return self._build_pair(asset, timeframe, up_market, down_market)

    def _build_pairs_from_parsing(self, markets: list[dict]) -> list[MarketPair]:
        """Construit des paires en parsant les questions des marches individuels."""
        # Grouper par (asset, timeframe, end_date)
        buckets: dict[tuple[str, str, str], dict[str, dict]] = {}

        for market in markets:
            question = market.get("question", "")
            asset = _parse_asset(question)
            direction = _parse_direction(question)
            timeframe = _parse_timeframe(question)
            end_date = market.get("end_date_iso", "")

            if not (asset and direction and timeframe and end_date):
                continue
            if asset not in self._target_assets or timeframe not in self._target_timeframes:
                continue

            key = (asset, timeframe, end_date)
            buckets.setdefault(key, {})
            buckets[key][direction] = market

        pairs: list[MarketPair] = []
        for (asset, timeframe, _), sides in buckets.items():
            if "up" in sides and "down" in sides:
                pair = self._build_pair(asset, timeframe, sides["up"], sides["down"])
                if pair:
                    pairs.append(pair)

        return pairs

    def _build_pair(self, asset: str, timeframe: str, up_market: dict, down_market: dict) -> Optional[MarketPair]:
        """Construit un MarketPair a partir de deux marches Up et Down."""
        try:
            token_id_up = self._extract_token_id(up_market)
            token_id_down = self._extract_token_id(down_market)

            end_date_str = up_market.get("end_date_iso", down_market.get("end_date_iso", ""))
            if not end_date_str:
                return None

            resolution_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            pair_id = f"{asset}_{timeframe}_{end_date_str}"

            return MarketPair(
                pair_id=pair_id,
                asset=asset,
                timeframe=timeframe,
                token_id_up=token_id_up,
                token_id_down=token_id_down,
                condition_id_up=up_market.get("condition_id", ""),
                condition_id_down=down_market.get("condition_id", ""),
                resolution_time=resolution_time,
            )
        except (KeyError, ValueError, IndexError) as e:
            logger.warning("Failed to build pair %s %s: %s", asset, timeframe, e)
            return None

    @staticmethod
    def _extract_token_id(market: dict) -> str:
        """Extrait le token_id Yes d'un marche."""
        tokens = market.get("tokens", [])
        if tokens:
            # Le premier token avec outcome "Yes"
            for token in tokens:
                if token.get("outcome", "").lower() == "yes":
                    return token["token_id"]
            # Fallback: premier token
            return tokens[0]["token_id"]

        # Fallback: clobTokenIds
        clob_ids = market.get("clobTokenIds", [])
        if clob_ids:
            return clob_ids[0]

        raise ValueError(f"No token_id found for market {market.get('condition_id', 'unknown')}")

    @staticmethod
    def update_prices(pair: MarketPair, book_up: dict, book_down: dict) -> MarketPair:
        """Retourne une nouvelle MarketPair avec les prix mis a jour depuis les orderbooks."""
        best_ask_up = _extract_best_ask(book_up)
        best_ask_down = _extract_best_ask(book_down)
        ask_size_up = _extract_ask_size(book_up)
        ask_size_down = _extract_ask_size(book_down)

        # Midpoint
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
            last_update=datetime.utcnow(),
        )


def _extract_best_ask(book: dict) -> float:
    asks = book.get("asks", [])
    if not asks:
        return 0.0
    return float(asks[0].get("price", 0))


def _extract_best_bid(book: dict) -> float:
    bids = book.get("bids", [])
    if not bids:
        return 0.0
    return float(bids[0].get("price", 0))


def _extract_ask_size(book: dict) -> float:
    asks = book.get("asks", [])
    if not asks:
        return 0.0
    return float(asks[0].get("size", 0))
