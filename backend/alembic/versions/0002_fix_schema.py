"""Fix schema: drop 0001 tables, create correct tables matching ORM.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-23 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Drop stale artefacts from 0001 (wrong schema) and any ORM create_all extras ──
    for view in ["ohlcv_1d", "ohlcv_4h", "ohlcv_1h", "ohlcv_15m", "ohlcv_5m"]:
        conn.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE"))

    for tbl in [
        # Tables created by migration 0001 (wrong names / wrong schema)
        "trader_heartbeats", "audit_log", "risk_settings",
        "positions", "orders", "backtest_results",
        "model_artifacts", "strategies", "ohlcv_bars", "users",
        # Tables that init_db() (create_all) may have created with correct ORM names
        # but possibly partial schema — drop and rebuild cleanly
        "trader_heartbeat", "model_registry", "ohlcv",
    ]:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))

    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="TRUE"),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default="FALSE"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ── ohlcv ────────────────────────────────────────────────────────────────
    op.create_table(
        "ohlcv",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol",   sa.String(32), nullable=False),
        sa.Column("ts",       sa.DateTime(timezone=True), nullable=False),
        sa.Column("open",     sa.Float, nullable=False),
        sa.Column("high",     sa.Float, nullable=False),
        sa.Column("low",      sa.Float, nullable=False),
        sa.Column("close",    sa.Float, nullable=False),
        sa.Column("volume",   sa.Float, nullable=False),
        sa.Column("source_quality", sa.SmallInteger, nullable=False,
                  server_default="1"),
        sa.UniqueConstraint("exchange", "symbol", "ts",
                            name="uq_ohlcv_exchange_symbol_ts"),
    )
    op.create_index("ix_ohlcv_exchange_symbol_ts", "ohlcv",
                    ["exchange", "symbol", "ts"])

    # TimescaleDB hypertable — savepoints so failures don't abort the transaction
    conn.execute(sa.text("SAVEPOINT ts_ext_0002"))
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        conn.execute(sa.text("RELEASE SAVEPOINT ts_ext_0002"))
        has_timescale = True
    except Exception:
        conn.execute(sa.text("ROLLBACK TO SAVEPOINT ts_ext_0002"))
        has_timescale = False

    if has_timescale:
        conn.execute(sa.text("SAVEPOINT ts_hyper_0002"))
        try:
            conn.execute(sa.text(
                "SELECT create_hypertable('ohlcv', 'ts', "
                "if_not_exists => TRUE, "
                "chunk_time_interval => INTERVAL '7 days')"
            ))
            conn.execute(sa.text("RELEASE SAVEPOINT ts_hyper_0002"))
        except Exception:
            conn.execute(sa.text("ROLLBACK TO SAVEPOINT ts_hyper_0002"))

    # ── strategies ───────────────────────────────────────────────────────────
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name",      sa.String(128), unique=True, nullable=False),
        sa.Column("paradigm",  sa.String(32),  nullable=False),
        sa.Column("symbol",    sa.String(32),  nullable=False),
        sa.Column("timeframe", sa.String(16),  nullable=False),
        sa.Column("config",    sa.JSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("status",    sa.String(32), nullable=False,
                  server_default=sa.text("'inactive'")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_strategies_name", "strategies", ["name"], unique=True)

    # ── model_registry ───────────────────────────────────────────────────────
    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_set_version", sa.Integer, nullable=False,
                  server_default="1"),
        sa.Column("git_sha",      sa.String(64), nullable=True),
        sa.Column("metrics",      sa.JSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("artifact_path", sa.Text, nullable=False),
        sa.Column("is_champion",  sa.Boolean, nullable=False,
                  server_default="FALSE"),
        sa.Column("model_type",   sa.String(64), nullable=False),
        sa.Column("created_at",   sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_model_registry_strategy_id", "model_registry",
                    ["strategy_id"])

    # ── orders ───────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_order_id",   sa.String(128), unique=True, nullable=False),
        sa.Column("exchange_order_id", sa.String(128), nullable=True),
        sa.Column("strategy_id",       postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol",            sa.String(32),  nullable=False),
        sa.Column("side",              sa.String(8),   nullable=False),
        sa.Column("order_type",        sa.String(16),  nullable=False),
        sa.Column("qty",               sa.Numeric(28, 8), nullable=False),
        sa.Column("price",             sa.Numeric(28, 8), nullable=True),
        sa.Column("filled_qty",        sa.Numeric(28, 8), nullable=False,
                  server_default="0"),
        sa.Column("avg_fill_price",    sa.Numeric(28, 8), nullable=True),
        sa.Column("status",            sa.String(16), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("fee",               sa.Numeric(28, 8), nullable=False,
                  server_default="0"),
        sa.Column("fee_currency",      sa.String(16), nullable=True),
        sa.Column("reduce_only",       sa.Boolean, nullable=False,
                  server_default="FALSE"),
        sa.Column("exchange",          sa.String(32), nullable=False),
        sa.Column("created_at",        sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at",        sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_orders_client_order_id",   "orders",
                    ["client_order_id"], unique=True)
    op.create_index("ix_orders_exchange_order_id", "orders",
                    ["exchange_order_id"])
    op.create_index("ix_orders_strategy_id",       "orders", ["strategy_id"])
    op.create_index("ix_orders_symbol",            "orders", ["symbol"])

    # ── positions ────────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol",          sa.String(32), unique=True, nullable=False),
        sa.Column("exchange",        sa.String(32), nullable=False),
        sa.Column("qty",             sa.Numeric(28, 8), nullable=False),
        sa.Column("avg_entry_price", sa.Numeric(28, 8), nullable=False),
        sa.Column("unrealized_pnl",  sa.Numeric(28, 8), nullable=False,
                  server_default="0"),
        sa.Column("realized_pnl",    sa.Numeric(28, 8), nullable=False,
                  server_default="0"),
        sa.Column("created_at",      sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at",      sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"], unique=True)

    # ── backtest_results ─────────────────────────────────────────────────────
    op.create_table(
        "backtest_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("strategy_id",  postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id",     postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("config",       sa.JSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("metrics",      sa.JSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("equity_curve", sa.JSON, nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("trade_log",    sa.JSON, nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("created_at",   sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_backtest_results_strategy_id", "backtest_results",
                    ["strategy_id"])
    op.create_index("ix_backtest_results_model_id", "backtest_results",
                    ["model_id"])

    # ── audit_log ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts",               sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("event_type",       sa.String(32), nullable=False),
        sa.Column("client_order_id",  sa.String(128), nullable=True),
        sa.Column("exchange_order_id", sa.String(128), nullable=True),
        sa.Column("strategy_id",      postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload",          sa.JSON, nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column("payload_hash",     sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_log_ts",         "audit_log", ["ts"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])

    # ── risk_settings (singleton row id=1) ───────────────────────────────────
    op.create_table(
        "risk_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("max_daily_loss_pct",        sa.Float, nullable=False,
                  server_default="0.03"),
        sa.Column("max_drawdown_pct",          sa.Float, nullable=False,
                  server_default="0.10"),
        sa.Column("max_position_notional_pct", sa.Float, nullable=False,
                  server_default="1.0"),
        sa.Column("max_open_orders",    sa.Integer, nullable=False,
                  server_default="5"),
        sa.Column("max_order_rate_per_min", sa.Integer, nullable=False,
                  server_default="30"),
        sa.Column("symbol_whitelist",   sa.JSON, nullable=False),
        sa.Column("leverage_limit",     sa.Float, nullable=False,
                  server_default="1.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    conn.execute(sa.text(
        "INSERT INTO risk_settings (id, symbol_whitelist) "
        "VALUES (1, '[\"BTC/GBP\",\"BTC/USDT\"]') "
        "ON CONFLICT DO NOTHING"
    ))

    # ── trader_heartbeat (single row keyed by 'main') ────────────────────────
    op.create_table(
        "trader_heartbeat",
        sa.Column("key", sa.String(16), primary_key=True),
        sa.Column("ts",  sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("loop_latency_ms",  sa.Float,   nullable=False,
                  server_default="0.0"),
        sa.Column("ws_connected",     sa.Boolean, nullable=False,
                  server_default="FALSE"),
        sa.Column("strategies_active", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("equity",    sa.Float, nullable=False, server_default="0.0"),
        sa.Column("daily_pnl", sa.Float, nullable=False, server_default="0.0"),
    )


def downgrade() -> None:
    for tbl in [
        "trader_heartbeat", "risk_settings", "audit_log",
        "backtest_results", "positions", "orders",
        "model_registry", "strategies", "ohlcv", "users",
    ]:
        op.drop_table(tbl)
