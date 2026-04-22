"""SQLAlchemy ORM models (SQLAlchemy 2.0 mapped_column style).

TimescaleDB hypertable setup and continuous aggregates are applied in the
Alembic migration (0001_initial.py); this module only defines ORM mappings.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ---------------------------------------------------------------------------
# OHLCV
# ---------------------------------------------------------------------------


class OHLCVBar(Base):
    """One OHLCV bar for a given symbol / exchange.

    The ``ts`` column is the TimescaleDB hypertable dimension column.
    Table name is ``ohlcv`` as required by the migration and continuous
    aggregate views.
    """

    __tablename__ = "ohlcv"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    exchange: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)

    # 1 = real data, 0 = gap-filled synthetic bar
    source_quality: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", "ts", name="uq_ohlcv_exchange_symbol_ts"),
        Index("ix_ohlcv_exchange_symbol_ts", "exchange", "symbol", "ts"),
    )

    def __repr__(self) -> str:
        return (
            f"<OHLCVBar {self.exchange}/{self.symbol} {self.ts} "
            f"o={self.open} c={self.close}>"
        )


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class Strategy(Base):
    """Trading strategy definition and state."""

    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # "supervised" | "deep_learning" | "rl"
    paradigm: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    # StrategyConfig serialised as JSON
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # "inactive" | "active" | "paper" | "backtesting" | "training"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="inactive")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Strategy {self.name} ({self.status})>"


# ---------------------------------------------------------------------------
# ModelArtifact
# ---------------------------------------------------------------------------


class ModelArtifact(Base):
    """Trained model artefact registry entry."""

    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    feature_set_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # {"sharpe": float, "sortino": float, "max_dd": float, ...}
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Relative path to .joblib or .pt file
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_champion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ModelArtifact {self.model_type} strategy={self.strategy_id} "
            f"champion={self.is_champion}>"
        )


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class Order(Base):
    """Exchange order record."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    client_order_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    exchange_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # "buy" | "sell"
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    # "market" | "limit" | "stop_limit"
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=28, scale=8), nullable=True
    )
    filled_qty: Mapped[Decimal] = mapped_column(
        Numeric(precision=28, scale=8), nullable=False, default=Decimal("0")
    )
    avg_fill_price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=28, scale=8), nullable=True
    )
    # "pending" | "open" | "filled" | "cancelled" | "rejected"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=28, scale=8), nullable=False, default=Decimal("0")
    )
    fee_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Order {self.client_order_id} {self.side} {self.qty} {self.symbol} "
            f"({self.status})>"
        )


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


class Position(Base):
    """Live position tracker (one row per symbol per exchange)."""

    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Unique index enforces one open position per symbol
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    # Negative quantity = short position
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    avg_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=28, scale=8), nullable=False
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=28, scale=8), nullable=False, default=Decimal("0")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=28, scale=8), nullable=False, default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Position {self.symbol} qty={self.qty} entry={self.avg_entry_price}>"


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------


class BacktestResult(Base):
    """Persisted backtest run results."""

    __tablename__ = "backtest_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # {"sharpe": float, "sortino": float, "calmar": float, "max_dd": float,
    #  "cagr": float, "hit_rate": float, "profit_factor": float,
    #  "psr": float, "dsr": float}
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # List of {"ts": iso_str, "equity": float, "drawdown": float}
    equity_curve: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # List of trade dicts
    trade_log: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<BacktestResult strategy={self.strategy_id} id={self.id}>"


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Immutable event log for all order / risk events.

    ``payload_hash`` is the SHA-256 of the JSON-serialised payload so entries
    can be verified offline.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # SIGNAL | ORDER_ATTEMPT | ORDER_FILL | ORDER_CANCEL |
    # RISK_GATE_REJECT | KILL_SWITCH | RECONCILIATION
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # SHA-256 hex digest of orjson.dumps(payload)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    def __repr__(self) -> str:
        return f"<AuditLog {self.event_type} ts={self.ts}>"


# ---------------------------------------------------------------------------
# RiskSettings
# ---------------------------------------------------------------------------


class RiskSettings(Base):
    """Singleton row (id=1) holding runtime risk limits.

    Application reads this at startup and on each order gate check.
    Updating this row via the /api/risk/settings PATCH endpoint takes effect
    for subsequent checks without a restart.
    """

    __tablename__ = "risk_settings"

    # Singleton – always id=1
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    max_daily_loss_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.03)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.10)
    max_position_notional_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )
    max_open_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_order_rate_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # JSON array of allowed symbols, e.g. ["BTC/GBP", "BTC/USDT"]
    symbol_whitelist: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: ["BTC/GBP", "BTC/USDT"]
    )
    leverage_limit: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<RiskSettings max_daily_loss={self.max_daily_loss_pct} "
            f"max_dd={self.max_drawdown_pct}>"
        )


# ---------------------------------------------------------------------------
# TraderHeartbeat
# ---------------------------------------------------------------------------


class TraderHeartbeat(Base):
    """Single-row liveness record written by the live trader loop.

    The backend /health/trader endpoint reads this (or its Redis copy) to
    determine whether the trader process is healthy.
    """

    __tablename__ = "trader_heartbeat"

    # Single row keyed by a fixed string "main"
    key: Mapped[str] = mapped_column(String(16), primary_key=True, default="main")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    loop_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ws_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    strategies_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    def __repr__(self) -> str:
        return (
            f"<TraderHeartbeat ts={self.ts} ws={self.ws_connected} "
            f"equity={self.equity}>"
        )


# ---------------------------------------------------------------------------
# User (for JWT auth)
# ---------------------------------------------------------------------------


class User(Base):
    """Application user for JWT authentication."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"
