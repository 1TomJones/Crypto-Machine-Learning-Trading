"""Pydantic v2 schemas for all API request/response models."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _OrmBase(BaseModel):
    """Base with ORM mode enabled for all response schemas."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# OHLCV
# ---------------------------------------------------------------------------


class OHLCVSchema(_OrmBase):
    id: int
    exchange: str
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_quality: int


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class StrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    paradigm: Literal["supervised", "deep_learning", "rl"]
    symbol: str = Field(..., min_length=1, max_length=32)
    timeframe: str = Field(..., min_length=1, max_length=16)
    config: dict[str, Any] = Field(default_factory=dict)


class StrategyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    paradigm: Literal["supervised", "deep_learning", "rl"] | None = None
    symbol: str | None = Field(None, min_length=1, max_length=32)
    timeframe: str | None = Field(None, min_length=1, max_length=16)
    config: dict[str, Any] | None = None
    status: Literal["inactive", "active", "paper", "backtesting", "training"] | None = None


class StrategyResponse(_OrmBase):
    id: uuid.UUID
    name: str
    paradigm: str
    symbol: str
    timeframe: str
    config: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Model artifacts
# ---------------------------------------------------------------------------


class ModelArtifactResponse(_OrmBase):
    id: uuid.UUID
    strategy_id: uuid.UUID
    feature_set_version: int
    git_sha: str | None
    metrics: dict[str, Any]
    artifact_path: str
    is_champion: bool
    model_type: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class OrderCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop_limit"]
    qty: Decimal = Field(..., gt=0)
    price: Decimal | None = None
    strategy_id: uuid.UUID | None = None
    reduce_only: bool = False
    exchange: str = Field(..., min_length=1, max_length=32)

    @field_validator("price")
    @classmethod
    def price_required_for_limit(cls, v: Decimal | None, info: Any) -> Decimal | None:
        order_type = info.data.get("order_type")
        if order_type in ("limit", "stop_limit") and v is None:
            raise ValueError("price is required for limit and stop_limit orders")
        return v


class OrderResponse(_OrmBase):
    id: uuid.UUID
    client_order_id: str
    exchange_order_id: str | None
    strategy_id: uuid.UUID | None
    symbol: str
    side: str
    order_type: str
    qty: Decimal
    price: Decimal | None
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    status: str
    fee: Decimal
    fee_currency: str | None
    reduce_only: bool
    exchange: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class PositionResponse(_OrmBase):
    id: uuid.UUID
    symbol: str
    exchange: str
    qty: Decimal
    avg_entry_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    strategy_id: uuid.UUID
    model_id: uuid.UUID | None = None
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(default=10_000.0, gt=0)
    commission_pct: float = Field(default=0.001, ge=0, le=0.05)
    slippage_bps: float = Field(default=2.0, ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class EquityPoint(BaseModel):
    ts: datetime
    equity: float
    drawdown: float


class TradeSummary(BaseModel):
    entry_ts: datetime
    exit_ts: datetime | None
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float | None
    pnl: float
    commission: float


class BacktestResponse(_OrmBase):
    id: uuid.UUID
    strategy_id: uuid.UUID
    model_id: uuid.UUID | None
    config: dict[str, Any]
    metrics: dict[str, Any]
    equity_curve: list[EquityPoint]
    trade_log: list[TradeSummary]
    created_at: datetime


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


class RiskSettingsUpdate(BaseModel):
    max_daily_loss_pct: float | None = Field(None, gt=0, le=1)
    max_drawdown_pct: float | None = Field(None, gt=0, le=1)
    max_position_notional_pct: float | None = Field(None, gt=0)
    max_open_orders: int | None = Field(None, ge=1, le=100)
    max_order_rate_per_min: int | None = Field(None, ge=1, le=600)
    symbol_whitelist: list[str] | None = None
    leverage_limit: float | None = Field(None, ge=1.0, le=100.0)


class RiskSettingsResponse(_OrmBase):
    id: int
    max_daily_loss_pct: float
    max_drawdown_pct: float
    max_position_notional_pct: float
    max_open_orders: int
    max_order_rate_per_min: int
    symbol_whitelist: list[str]
    leverage_limit: float
    updated_at: datetime


class RiskMetricsResponse(BaseModel):
    var_95: float
    expected_shortfall_95: float
    daily_pnl: float
    equity: float
    open_positions: int
    open_orders: int
    daily_loss_pct: float
    current_drawdown_pct: float
    timestamp: datetime


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"]
    timestamp: datetime
    environment: str


class TraderHealthResponse(BaseModel):
    status: Literal["ok", "stale", "unavailable"]
    ts: datetime | None
    loop_latency_ms: float | None
    ws_connected: bool | None
    strategies_active: int | None
    equity: float | None
    daily_pnl: float | None
    stale_seconds: float | None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds


# ---------------------------------------------------------------------------
# Walk-forward CV config (§10)
# ---------------------------------------------------------------------------


class WalkForwardCV(BaseModel):
    n_splits: int = Field(default=5, ge=2, le=20)
    train_periods: int = Field(default=252, ge=30)
    test_periods: int = Field(default=63, ge=5)
    gap_periods: int = Field(default=1, ge=0)
    purge_periods: int = Field(default=5, ge=0)


# ---------------------------------------------------------------------------
# Model hyper-parameter schemas (§10)
# ---------------------------------------------------------------------------


class XGBoostParams(BaseModel):
    n_estimators: int = Field(default=500, ge=50, le=5000)
    max_depth: int = Field(default=6, ge=1, le=16)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    subsample: float = Field(default=0.8, gt=0, le=1)
    colsample_bytree: float = Field(default=0.8, gt=0, le=1)
    reg_alpha: float = Field(default=0.1, ge=0)
    reg_lambda: float = Field(default=1.0, ge=0)
    min_child_weight: int = Field(default=5, ge=1)
    gamma: float = Field(default=0.1, ge=0)
    scale_pos_weight: float = Field(default=1.0, gt=0)


class LSTMParams(BaseModel):
    hidden_size: int = Field(default=128, ge=16, le=1024)
    num_layers: int = Field(default=2, ge=1, le=8)
    dropout: float = Field(default=0.2, ge=0, lt=1)
    seq_len: int = Field(default=60, ge=10, le=500)
    batch_size: int = Field(default=64, ge=8, le=1024)
    learning_rate: float = Field(default=1e-3, gt=0)
    weight_decay: float = Field(default=1e-4, ge=0)
    max_epochs: int = Field(default=100, ge=1, le=1000)
    patience: int = Field(default=10, ge=1)


class PPOParams(BaseModel):
    learning_rate: float = Field(default=3e-4, gt=0)
    n_steps: int = Field(default=2048, ge=64)
    batch_size: int = Field(default=64, ge=8)
    n_epochs: int = Field(default=10, ge=1, le=50)
    gamma: float = Field(default=0.99, gt=0, le=1)
    gae_lambda: float = Field(default=0.95, gt=0, le=1)
    clip_range: float = Field(default=0.2, gt=0, lt=1)
    ent_coef: float = Field(default=0.01, ge=0)
    vf_coef: float = Field(default=0.5, gt=0)
    max_grad_norm: float = Field(default=0.5, gt=0)
    total_timesteps: int = Field(default=1_000_000, ge=10_000)


# ---------------------------------------------------------------------------
# StrategyConfig discriminated union (§10)
# ---------------------------------------------------------------------------


class SupervisedConfig(BaseModel):
    type: Literal["supervised"] = "supervised"
    model: Literal["xgboost", "lightgbm"] = "xgboost"
    xgboost_params: XGBoostParams = Field(default_factory=XGBoostParams)
    walk_forward: WalkForwardCV = Field(default_factory=WalkForwardCV)
    target_horizon_bars: int = Field(default=1, ge=1)
    signal_threshold: float = Field(default=0.55, gt=0.5, le=1.0)
    feature_set_version: int = Field(default=1, ge=1)


class DeepLearningConfig(BaseModel):
    type: Literal["deep_learning"] = "deep_learning"
    architecture: Literal["lstm", "transformer"] = "lstm"
    lstm_params: LSTMParams = Field(default_factory=LSTMParams)
    walk_forward: WalkForwardCV = Field(default_factory=WalkForwardCV)
    target_horizon_bars: int = Field(default=1, ge=1)
    signal_threshold: float = Field(default=0.55, gt=0.5, le=1.0)
    feature_set_version: int = Field(default=1, ge=1)


class RLConfig(BaseModel):
    type: Literal["rl"] = "rl"
    algorithm: Literal["ppo", "a2c", "sac"] = "ppo"
    ppo_params: PPOParams = Field(default_factory=PPOParams)
    walk_forward: WalkForwardCV = Field(default_factory=WalkForwardCV)
    feature_set_version: int = Field(default=1, ge=1)
    env_initial_balance: float = Field(default=10_000.0, gt=0)
    env_max_position_pct: float = Field(default=0.95, gt=0, le=1)


StrategyConfig = Annotated[
    Union[SupervisedConfig, DeepLearningConfig, RLConfig],
    Field(discriminator="type"),
]
