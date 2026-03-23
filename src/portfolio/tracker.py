"""
Portfolio tracker — etat central du bot.
Ecoute tous les events du bus et maintient l'etat a jour.
Expose les donnees pour le dashboard.
"""
import asyncio
import logging
from collections import deque, defaultdict
from datetime import datetime, timezone
from typing import Optional

from src.core.events import Event, EventBus
from src.core.models import Opportunity, PaperTrade, PortfolioState, TradeStatus

logger = logging.getLogger(__name__)

MAX_PRICE_HISTORY = 1000
MAX_OPPORTUNITIES = 200
MAX_PNL_SERIES = 500
MAX_CHART_POINTS = 300  # ~15 min a 3s/point


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

        # Per-pair price chart data: pair_id -> deque of {t, up, down, combined}
        self.chart_data: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_CHART_POINTS))

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
            # Feed chart data
            d = event.data
            pair_id = d["pair_id"]
            self.chart_data[pair_id].append({
                "t": datetime.now(timezone.utc).isoformat(),
                "up": d.get("best_ask_up", 0),
                "down": d.get("best_ask_down", 0),
                "combined": d.get("combined_cost", 0),
            })

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

    def get_chart_data(self, pair_id: Optional[str] = None) -> list[dict]:
        """Retourne les donnees du chart pour une paire (ou la premiere trouvee)."""
        if pair_id and pair_id in self.chart_data:
            return list(self.chart_data[pair_id])
        # Retourne les donnees de la premiere paire avec des points
        for pid, data in self.chart_data.items():
            if data:
                return list(data)
        return []

    def get_all_chart_series(self) -> dict[str, list[dict]]:
        """Retourne toutes les series de prix pour toutes les paires."""
        return {pid: list(data) for pid, data in self.chart_data.items() if data}
