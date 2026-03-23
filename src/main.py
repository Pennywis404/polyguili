"""
Point d'entree du bot.
Charge la config, cree tous les composants, et lance les taches en parallele.
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from src.core.config import load_config
from src.core.events import EventBus
from src.market.client import PolymarketClient
from src.market.monitor import MarketMonitor
from src.market.pairs import PairManager
from src.portfolio.persistence import auto_save_loop, load_state, save_state
from src.portfolio.tracker import PortfolioTracker
from src.strategy.detector import OpportunityDetector
from src.strategy.executor import PaperExecutor
from src.web.app import create_app


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Quieter libs
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger("polyarb")

    logger.info("=== Polymarket Temporal Arbitrage Bot ===")
    logger.info("Loading config...")

    # Ensure data directory exists
    Path(config.persistence.state_file).parent.mkdir(parents=True, exist_ok=True)

    # Load persisted state
    portfolio, trades, opportunities = load_state(
        config.persistence.state_file,
        default_capital=config.portfolio.initial_capital,
    )

    # Create event bus
    event_bus = EventBus()

    # Create API client
    client = PolymarketClient(
        clob_url=config.polymarket_api_url,
        gamma_url="https://gamma-api.polymarket.com",
    )

    # Create pair manager
    pair_manager = PairManager(target_assets=config.monitoring.assets)

    # Create monitor
    monitor = MarketMonitor(
        client=client,
        pair_manager=pair_manager,
        event_bus=event_bus,
        poll_interval=config.monitoring.poll_interval,
        pair_refresh_interval=config.monitoring.pair_refresh_interval,
    )

    # Create detector
    detector = OpportunityDetector(
        event_bus=event_bus,
        pairs_ref=monitor.active_pairs,
        trades=trades,
        portfolio_active_positions=portfolio.active_positions,
        capital_per_trade=config.strategy.capital_per_trade,
        min_time_to_resolution=config.strategy.min_time_to_resolution,
        min_liquidity=config.strategy.min_liquidity,
    )

    # Create executor
    executor = PaperExecutor(
        event_bus=event_bus,
        portfolio=portfolio,
        trades=trades,
        pairs_ref=monitor.active_pairs,
        capital_per_trade=config.strategy.capital_per_trade,
        max_concurrent_positions=config.strategy.max_concurrent_positions,
        min_time_to_resolution=config.strategy.min_time_to_resolution,
        min_liquidity=config.strategy.min_liquidity,
    )

    # Create tracker
    tracker = PortfolioTracker(
        portfolio=portfolio,
        trades=trades,
        event_bus=event_bus,
    )
    # Load past opportunities
    for opp in opportunities:
        tracker.opportunities.append(opp)

    # Create web app
    app = create_app(tracker=tracker, event_bus=event_bus, pairs_ref=monitor.active_pairs)

    # Uvicorn config
    uvi_config = uvicorn.Config(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level="warning",
    )
    server = uvicorn.Server(uvi_config)

    # Shutdown handler
    shutdown_event = asyncio.Event()

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("Shutdown signal received (%s)", sig.name)
        monitor.stop()
        detector.stop()
        executor.stop()
        tracker.stop()
        server.should_exit = True
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    logger.info("Starting bot components...")
    logger.info("Dashboard: http://%s:%d", config.web.host, config.web.port)
    logger.info("Paper trading ready. Capital: $%.2f", portfolio.current_capital)

    # Launch all tasks
    async with client:
        tasks = [
            asyncio.create_task(monitor.run(), name="monitor"),
            asyncio.create_task(detector.run(), name="detector"),
            asyncio.create_task(executor.run(), name="executor"),
            asyncio.create_task(tracker.run(), name="tracker"),
            asyncio.create_task(
                auto_save_loop(
                    config.persistence.state_file,
                    portfolio,
                    trades,
                    tracker.opportunities,
                    config.persistence.dump_interval,
                ),
                name="autosave",
            ),
            asyncio.create_task(server.serve(), name="web"),
        ]

        # Wait for shutdown
        await shutdown_event.wait()

        # Cancel all tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Final save
    if config.persistence.backup_on_shutdown:
        logger.info("Saving state before exit...")
        save_state(config.persistence.state_file, portfolio, trades, tracker.opportunities)

    logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
