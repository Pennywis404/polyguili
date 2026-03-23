from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    UP = "up"
    DOWN = "down"


class TradeStatus(str, Enum):
    LEG1_OPEN = "leg1_open"
    FULLY_HEDGED = "fully_hedged"
    RESOLVED_WIN = "resolved_win"
    RESOLVED_LOSS = "resolved_loss"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class MarketPair:
    """Une paire de marches Up/Down pour un meme asset et timeframe."""
    pair_id: str
    asset: str
    timeframe: str
    token_id_up: str
    token_id_down: str
    condition_id_up: str
    condition_id_down: str
    resolution_time: datetime
    price_up: float = 0.0
    price_down: float = 0.0
    best_ask_up: float = 0.0
    best_ask_down: float = 0.0
    ask_size_up: float = 0.0
    ask_size_down: float = 0.0
    last_update: Optional[datetime] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resolution_time"] = self.resolution_time.isoformat()
        if self.last_update:
            d["last_update"] = self.last_update.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MarketPair":
        data = dict(data)
        data["resolution_time"] = datetime.fromisoformat(data["resolution_time"])
        if data.get("last_update"):
            data["last_update"] = datetime.fromisoformat(data["last_update"])
        return cls(**data)


@dataclass
class Opportunity:
    """Une opportunite d'arbitrage detectee."""
    id: str
    pair_id: str
    asset: str
    timeframe: str
    leg1_side: Side
    leg1_price: float
    leg2_price: float
    timestamp: datetime
    combined_cost: float
    estimated_profit_pct: float
    available_liquidity: float
    status: str = "detected"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["leg1_side"] = self.leg1_side.value
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Opportunity":
        data = dict(data)
        data["leg1_side"] = Side(data["leg1_side"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class PaperTrade:
    """Un trade paper (simule)."""
    id: str
    pair_id: str
    asset: str
    timeframe: str

    # Leg 1
    leg1_side: Side
    leg1_price: float
    leg1_shares: float
    leg1_fee: float
    leg1_timestamp: datetime
    leg1_stake: float

    # Leg 2
    leg2_side: Optional[Side] = None
    leg2_price: Optional[float] = None
    leg2_shares: Optional[float] = None
    leg2_fee: Optional[float] = None
    leg2_timestamp: Optional[datetime] = None
    leg2_stake: Optional[float] = None

    # Resultat
    status: TradeStatus = TradeStatus.LEG1_OPEN
    capital_deployed: float = 0.0
    total_fees: float = 0.0
    payout: Optional[float] = None
    profit: Optional[float] = None
    roi: Optional[float] = None
    resolution_outcome: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_time: Optional[datetime] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["leg1_side"] = self.leg1_side.value
        d["leg1_timestamp"] = self.leg1_timestamp.isoformat()
        d["status"] = self.status.value
        if self.leg2_side:
            d["leg2_side"] = self.leg2_side.value
        if self.leg2_timestamp:
            d["leg2_timestamp"] = self.leg2_timestamp.isoformat()
        if self.resolved_at:
            d["resolved_at"] = self.resolved_at.isoformat()
        if self.resolution_time:
            d["resolution_time"] = self.resolution_time.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PaperTrade":
        data = dict(data)
        data["leg1_side"] = Side(data["leg1_side"])
        data["leg1_timestamp"] = datetime.fromisoformat(data["leg1_timestamp"])
        data["status"] = TradeStatus(data["status"])
        if data.get("leg2_side"):
            data["leg2_side"] = Side(data["leg2_side"])
        if data.get("leg2_timestamp"):
            data["leg2_timestamp"] = datetime.fromisoformat(data["leg2_timestamp"])
        if data.get("resolved_at"):
            data["resolved_at"] = datetime.fromisoformat(data["resolved_at"])
        if data.get("resolution_time"):
            data["resolution_time"] = datetime.fromisoformat(data["resolution_time"])
        return cls(**data)


@dataclass
class PortfolioState:
    """Etat courant du portfolio paper."""
    initial_capital: float = 10000.0
    current_capital: float = 10000.0
    total_deployed: float = 0.0
    total_pnl: float = 0.0
    total_fees_paid: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    active_positions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PortfolioState":
        return cls(**data)

    @property
    def win_rate(self) -> float:
        completed = self.winning_trades + self.losing_trades
        if completed == 0:
            return 0.0
        return self.winning_trades / completed * 100
