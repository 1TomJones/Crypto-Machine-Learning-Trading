"""Initial schema: all tables + TimescaleDB hypertable.

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="TRUE"),
        sa.Column("is_admin", sa.Boolean, server_default="FALSE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- OHLCV bars (TimescaleDB hypertable) ---
    op.create_table(
        "ohlcv_bars",
        sa.Column("ts",        sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol",    sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8),  nullable=False),
        sa.Column("open",      sa.Float, nullable=False),
        sa.Column("high",      sa.Float, nullable=False),
        sa.Column("low",       sa.Float, nullable=False),
        sa.Column("close",     sa.Float, nullable=False),
        sa.Column("volume",    sa.Float, nullable=False),
        sa.Column("source_quality", sa.Integer, server_default="1"),
        sa.PrimaryKeyConstraint("ts", "symbol", "timeframe"),
    )
    # Try to enable TimescaleDB + create hypertable (gracefully skip on vanilla Postgres)
    conn = op.get_bind()
    has_timescale = False
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        has_timescale = True
    except Exception:
        pass

    if has_timescale:
        op.execute(
            "SELECT create_hypertable('ohlcv_bars', 'ts', "
            "if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days')"
        )
    op.create_index("ix_ohlcv_symbol_tf_ts", "ohlcv_bars", ["symbol", "timeframe", "ts"])

    # --- Strategies ---
    op.create_table(
        "strategies",
        sa.Column("id",          sa.String(64), primary_key=True),
        sa.Column("name",        sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("config",      postgresql.JSONB, nullable=True),
        sa.Column("status",      sa.String(32), server_default=sa.text("'draft'")),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",  sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- Model Artifacts ---
    op.create_table(
        "model_artifacts",
        sa.Column("id",             sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("strategy_id",    sa.String(64), nullable=False),
        sa.Column("artifact_path",  sa.Text, nullable=False),
        sa.Column("strategy_type",  sa.String(32), nullable=False),
        sa.Column("cv_scores",      postgresql.JSONB, nullable=True),
        sa.Column("is_champion",    sa.Boolean, server_default="FALSE"),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- Backtest Results ---
    op.create_table(
        "backtest_results",
        sa.Column("id",          sa.String(64), primary_key=True),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("config",      postgresql.JSONB, nullable=True),
        sa.Column("results",     postgresql.JSONB, nullable=True),
        sa.Column("status",      sa.String(32), server_default=sa.text("'pending'")),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at",sa.DateTime(timezone=True), nullable=True),
    )

    # --- Orders ---
    op.create_table(
        "orders",
        sa.Column("id",                sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_order_id",   sa.String(64), unique=True, nullable=False),
        sa.Column("exchange_order_id", sa.String(64), nullable=True),
        sa.Column("strategy_id",       sa.String(64), nullable=True),
        sa.Column("symbol",            sa.String(32), nullable=False),
        sa.Column("side",              sa.String(8),  nullable=False),
        sa.Column("order_type",        sa.String(16), nullable=False),
        sa.Column("qty",               sa.Float, nullable=False),
        sa.Column("filled_qty",        sa.Float, server_default="0"),
        sa.Column("avg_fill_price",    sa.Float, nullable=True),
        sa.Column("price",             sa.Float, nullable=True),
        sa.Column("status",            sa.String(16), server_default=sa.text("'pending'")),
        sa.Column("reduce_only",       sa.Boolean, server_default="FALSE"),
        sa.Column("raw_data",          postgresql.JSONB, nullable=True),
        sa.Column("created_at",        sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",        sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- Positions ---
    op.create_table(
        "positions",
        sa.Column("id",           sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol",       sa.String(32), nullable=False, unique=True),
        sa.Column("strategy_id",  sa.String(64), nullable=True),
        sa.Column("qty",          sa.Float, nullable=False, server_default="0"),
        sa.Column("avg_price",    sa.Float, nullable=True),
        sa.Column("unrealized_pnl", sa.Float, nullable=True),
        sa.Column("updated_at",   sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- Risk Settings ---
    op.create_table(
        "risk_settings",
        sa.Column("id",                      sa.Integer, primary_key=True),
        sa.Column("max_daily_loss_pct",      sa.Float, server_default="0.03"),
        sa.Column("max_drawdown_pct",        sa.Float, server_default="0.10"),
        sa.Column("max_position_notional_pct", sa.Float, server_default="1.0"),
        sa.Column("max_open_orders",         sa.Integer, server_default="5"),
        sa.Column("max_order_rate_per_min",  sa.Integer, server_default="30"),
        sa.Column("leverage_limit",          sa.Float, server_default="1.0"),
        sa.Column("symbol_whitelist",        postgresql.JSONB, server_default=sa.text("'[\"BTC/USDT\"]'::jsonb")),
        sa.Column("updated_at",              sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    # Insert default row (id=1)
    op.execute("INSERT INTO risk_settings (id) VALUES (1) ON CONFLICT DO NOTHING")

    # --- Audit Log ---
    op.create_table(
        "audit_log",
        sa.Column("id",         sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id",    sa.Integer, nullable=True),
        sa.Column("action",     sa.String(128), nullable=False),
        sa.Column("target",     sa.String(128), nullable=True),
        sa.Column("detail",     postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- Trader Heartbeat ---
    op.create_table(
        "trader_heartbeats",
        sa.Column("id",              sa.Integer, primary_key=True),
        sa.Column("ts",              sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("trading_enabled", sa.Boolean, server_default="FALSE"),
        sa.Column("equity",          sa.Float, nullable=True),
        sa.Column("status",          sa.String(32), server_default=sa.text("'stopped'")),
    )

    # --- Continuous aggregate views for 5m/15m/1h/4h/1d (TimescaleDB only) ---
    # Requires the Timescale license; the Apache-licensed build (e.g. Render)
    # supports hypertables but not continuous aggregates — skip gracefully.
    if has_timescale:
        try:
            for bucket, name in [
                ("5 minutes",  "ohlcv_5m"),
                ("15 minutes", "ohlcv_15m"),
                ("1 hour",     "ohlcv_1h"),
                ("4 hours",    "ohlcv_4h"),
                ("1 day",      "ohlcv_1d"),
            ]:
                op.execute(f"""
                CREATE MATERIALIZED VIEW IF NOT EXISTS {name}
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('{bucket}', ts) AS bucket,
                    symbol,
                    first(open,  ts) AS open,
                    max(high)        AS high,
                    min(low)         AS low,
                    last(close, ts)  AS close,
                    sum(volume)      AS volume
                FROM ohlcv_bars
                WHERE timeframe = '1m'
                GROUP BY bucket, symbol
                WITH NO DATA;
                """)
        except Exception:
            pass  # Apache-licensed TimescaleDB; continuous aggregates not available


def downgrade() -> None:
    for name in ["ohlcv_1d", "ohlcv_4h", "ohlcv_1h", "ohlcv_15m", "ohlcv_5m"]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
    for table in [
        "trader_heartbeats", "audit_log", "risk_settings",
        "positions", "orders", "backtest_results", "model_artifacts",
        "strategies", "ohlcv_bars", "users",
    ]:
        op.drop_table(table)
