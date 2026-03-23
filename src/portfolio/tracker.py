"""
Portfolio tracker — etat central du bot.
Ecoute tous les events du bus et maintient l'etat a jour.
Expose les donnees pour le dashboard.
"""
import asyncio
import logging
from collections import deque, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.models import Opportunity, PaperTrade, PortfolioState, TradeStatus

logger = logging.getLogger(__name__)

MAX_PRICE_HISTORY = 1000
MAX_OPPORTUNITIES = 200
MAX_PNL_SERIES = 500


class PortfolioTracker:
    def __init__(
        self,
        portfolio: PortfolioState,
        trades: dict[str, PaperTrade],
        event_bus: EventBus,
    ) -> None:
        self.portfolio = portfolio
        self.trades = trades
        self._event_bus = event_bus
        self.opportunities: deque[Opportunity] = deque(maxlen=MAX_OPPORTUNITIES)
        self.price_history: deque[dict] = deque(maxlen=MAX_PRICE_HISTORY)
        self.pnl_series: deque[dict] = deque(maxlen=MAX_PNL_SERIES)
        self._running = False

        # Chart data per ASSET — tracks the CURRENT active 5min slot only
        # asset -> list of {s: seconds_elapsed, up: float, down: float}
        self.chart_data: dict[str, list[dict]] = defaultdict(list)
        # Track which slot (pair_id) is active per asset
        self._active_slot: dict[str, str] = {}
        # Resolution time of active slot per asset
        self._active_slot_resolution: dict[str, str] = {}
        # Latest prices per asset (for display)
        self._latest_price: dict[str, dict] = {}

        # Snapshot initial du P&L
        self.pnl_series.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pnl": self.portfolio.total_pnl,
            "capital": self.portfolio.current_capital,
        })

    async def run(self) -> None:
        self._running = True
        queue = await self._event_bus.subscribe()
        logger.info("PortfolioTracker started")

        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                self._handle_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Tracker error: %s", e, exc_info=True)

    def stop(self) -> None:
        self._running = False

    def _handle_event(self, event: Event) -> None:
        if event.type == "price_update":
            self.price_history.append(event.data)
            self._process_chart_point(event.data)

        elif event.type == "opportunity_detected":
            try:
                opp = Opportunity.from_dict(event.data)
                self.opportunities.append(opp)
            except Exception as e:
                logger.warning("Failed to parse opportunity: %s", e)

        elif event.type == "trade_resolved":
            self.pnl_series.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pnl": self.portfolio.total_pnl,
                "capital": self.portfolio.current_capital,
            })

    def _process_chart_point(self, data: dict) -> None:
        """Process a price update into a chart point with elapsed seconds."""
        asset = data.get("asset", "")
        pair_id = data.get("pair_id", "")
        resolution = data.get("resolution_time", "")
        up = data.get("best_ask_up", 0)
        down = data.get("best_ask_down", 0)

        if not asset or not resolution:
            return
        # Skip garbage prices
        if up < 0.01 or down < 0.01 or up > 0.99 or down > 0.99:
            return

        now = datetime.now(timezone.utc)

        # Determine the active slot for this asset:
        # Pick the slot closest to resolution that hasn't expired yet
        try:
            res_dt = datetime.fromisoformat(resolution)
        except (ValueError, TypeError):
            return

        if res_dt < now:
            return  # Already expired

        current_slot = self._active_slot.get(asset)
        current_res = self._active_slot_resolution.get(asset, "")

        if current_slot is None:
            # First slot for this asset
            self._active_slot[asset] = pair_id
            self._active_slot_resolution[asset] = resolution
            self.chart_data[asset] = []
        elif pair_id != current_slot:
            # Different pair_id — check if current slot expired
            try:
                current_res_dt = datetime.fromisoformat(current_res)
                if now >= current_res_dt:
                    # Current slot expired → switch to new slot, RESET chart
                    self._active_slot[asset] = pair_id
                    self._active_slot_resolution[asset] = resolution
                    self.chart_data[asset] = []
                    logger.info("Chart reset for %s — new slot %s", asset, pair_id[:20])
                elif resolution < current_res:
                    # This pair resolves sooner → switch to it
                    self._active_slot[asset] = pair_id
                    self._active_slot_resolution[asset] = resolution
                    self.chart_data[asset] = []
                else:
                    return  # This is a future slot, ignore
            except (ValueError, TypeError):
                return

        # Only record points from the active slot
        if pair_id != self._active_slot.get(asset):
            return

        # Calculate seconds elapsed since market start (resolution - 5min)
        market_start = res_dt - timedelta(minutes=5)
        elapsed = (now - market_start).total_seconds()
        elapsed = max(0.0, min(300.0, elapsed))

        self.chart_data[asset].append({
            "s": round(elapsed, 1),
            "up": up,
            "down": down,
        })

        # Store latest price
        self._latest_price[asset] = {
            "up": up,
            "down": down,
            "resolution_time": resolution,
            "pair_id": pair_id,
            "elapsed": elapsed,
        }

    # --- Methodes de requete pour le dashboard ---

    def get_active_trades(self) -> list[PaperTrade]:
        return [
            self.trades[tid]
            for tid in self.portfolio.active_positions
            if tid in self.trades
        ]

    def get_trade_history(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[PaperTrade]:
        trades = list(self.trades.values())
        if asset:
            trades = [t for t in trades if t.asset == asset]
        if timeframe:
            trades = [t for t in trades if t.timeframe == timeframe]
        if status:
            trades = [t for t in trades if t.status.value == status]
        return sorted(trades, key=lambda t: t.leg1_timestamp, reverse=True)

    def get_portfolio_summary(self) -> dict:
        return {
            **self.portfolio.to_dict(),
            "win_rate": self.portfolio.win_rate,
        }

    def get_recent_opportunities(self, limit: int = 20) -> list[dict]:
        opps = list(self.opportunities)[-limit:]
        return [o.to_dict() for o in reversed(opps)]

    def get_pnl_data(self) -> list[dict]:
        return list(self.pnl_series)

    def get_latest_prices(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for entry in self.price_history:
            latest[entry["pair_id"]] = entry
        return latest

    def get_chart_data(self, asset: Optional[str] = None) -> dict:
        """Retourne les donnees du chart pour un asset avec metadonnees du slot."""
        target = asset or next(iter(self._active_slot), None)
        if not target:
            return {"points": [], "asset": "", "resolution_time": "", "elapsed": 0, "total": 300}

        resolution = self._active_slot_resolution.get(target, "")
        latest = self._latest_price.get(target, {})
        elapsed = latest.get("elapsed", 0)

        return {
            "points": list(self.chart_data.get(target, [])),
            "asset": target,
            "resolution_time": resolution,
            "elapsed": round(elapsed, 1),
            "total": 300,
            "current_up": latest.get("up", 0),
            "current_down": latest.get("down", 0),
        }

    def get_available_assets(self) -> list[dict]:
        """Liste des assets avec des donnees de chart."""
        result = []
        for asset in sorted(self._active_slot.keys()):
            latest = self._latest_price.get(asset, {})
            result.append({
                "asset": asset,
                "points": len(self.chart_data.get(asset, [])),
                "up": latest.get("up", 0),
                "down": latest.get("down", 0),
            })
        return result
