from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class StrategyConfig:
    simultaneous_arb_threshold: float = 0.98
    leg1_max_price: float = 0.52
    combined_cost_target: float = 0.97
    capital_per_trade: float = 100.0
    max_concurrent_positions: int = 5
    min_time_to_resolution: int = 120
    max_leg1_hold_time: int = 300
    min_liquidity: float = 50.0


@dataclass(frozen=True)
class MonitoringConfig:
    poll_interval: int = 3
    pair_refresh_interval: int = 60
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")
    timeframes: tuple[str, ...] = ("5min", "15min")


@dataclass(frozen=True)
class PortfolioConfig:
    initial_capital: float = 10000.0


@dataclass(frozen=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass(frozen=True)
class PersistenceConfig:
    state_file: str = "data/state.json"
    dump_interval: int = 60
    backup_on_shutdown: bool = True


@dataclass(frozen=True)
class Config:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    web: WebConfig = field(default_factory=WebConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    polymarket_api_url: str = "https://clob.polymarket.com"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    log_level: str = "INFO"


def load_config(path: str = "config.yaml") -> Config:
    load_dotenv()

    yaml_data: dict = {}
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    strategy_raw = yaml_data.get("strategy", {})
    monitoring_raw = yaml_data.get("monitoring", {})
    portfolio_raw = yaml_data.get("portfolio", {})
    web_raw = yaml_data.get("web", {})
    persistence_raw = yaml_data.get("persistence", {})

    # Convert lists to tuples for frozen dataclass
    if "assets" in monitoring_raw and isinstance(monitoring_raw["assets"], list):
        monitoring_raw["assets"] = tuple(monitoring_raw["assets"])
    if "timeframes" in monitoring_raw and isinstance(monitoring_raw["timeframes"], list):
        monitoring_raw["timeframes"] = tuple(monitoring_raw["timeframes"])

    return Config(
        strategy=StrategyConfig(**strategy_raw),
        monitoring=MonitoringConfig(**monitoring_raw),
        portfolio=PortfolioConfig(**portfolio_raw),
        web=WebConfig(**web_raw),
        persistence=PersistenceConfig(**persistence_raw),
        polymarket_api_url=os.getenv("POLYMARKET_API_URL", "https://clob.polymarket.com"),
        polymarket_ws_url=os.getenv("POLYMARKET_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
