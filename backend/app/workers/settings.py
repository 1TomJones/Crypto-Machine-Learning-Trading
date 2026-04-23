"""arq WorkerSettings and task definitions for background jobs."""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Task: train_model
# ---------------------------------------------------------------------------

async def train_model(ctx: dict, job_id: str, strategy_id: str, params: dict) -> dict:
    """Train a new model artifact for the given strategy."""
    log.info("worker_train_model", job_id=job_id, strategy_id=strategy_id)
    settings = get_settings()

    try:
        import pandas as pd
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy import text

        engine = create_async_engine(settings.database_url)
        async with AsyncSession(engine) as session:
            # Load OHLCV
            symbol   = params.get("symbol", "BTC/USDT")
            tf       = params.get("timeframe", "1h")
            start    = params.get("start_date", "2020-01-01")
            end      = params.get("end_date", "2024-01-01")
            rows = await session.execute(text(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=:sym AND timeframe=:tf AND ts BETWEEN :s AND :e ORDER BY ts"
            ), {"sym": symbol, "tf": tf, "s": start, "e": end})
            df = pd.DataFrame(rows.fetchall(), columns=["ts","open","high","low","close","volume"])
            if df.empty:
                return {"error": "no data"}
            df.index = pd.to_datetime(df["ts"])

        from app.features.pipeline import compute_features
        from app.ml.labels import triple_barrier, daily_volatility, get_sample_weights
        from app.ml.supervised import GBMStrategy
        from app.ml.cv import PurgedKFold

        features = compute_features(df)
        vol = daily_volatility(df["close"])
        labels, _ = triple_barrier(
            df["close"], vol,
            pt_sl=[params.get("pt", 1.0), params.get("sl", 1.0)],
            max_hold=params.get("max_hold", 24),
        )
        labels = labels.dropna()
        X = features.loc[labels.index].dropna()
        y = labels.loc[X.index]
        weights = get_sample_weights(df["close"], labels.loc[X.index])

        model_type = params.get("model_type", "lightgbm")
        strategy = GBMStrategy(model_type=model_type, params=params.get("model_params", {}))
        cv = PurgedKFold(n_splits=5, embargo_td=pd.Timedelta(hours=24))
        scores = strategy.cross_validate(X, y, cv, weights)

        import tempfile, os, joblib
        artifact_dir = settings.model_artifact_path or "/tmp/artifacts"
        os.makedirs(artifact_dir, exist_ok=True)
        path = os.path.join(artifact_dir, f"{strategy_id}_{job_id}.pkl")
        strategy.fit(X, y, weights)
        strategy.save(path)

        async with AsyncSession(engine) as session:
            await session.execute(text(
                "INSERT INTO model_registry (strategy_id, artifact_path, model_type, metrics, is_champion) "
                "VALUES (:sid, :path, :stype, :scores::jsonb, FALSE)"
            ), {
                "sid": strategy_id, "path": path, "stype": model_type,
                "scores": str(scores),
            })
            await session.commit()

        log.info("worker_train_done", job_id=job_id, path=path)
        return {"path": path, "metrics": scores}
    except Exception as exc:
        log.error("worker_train_error", job_id=job_id, error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Task: run_backtest
# ---------------------------------------------------------------------------

async def run_backtest(ctx: dict, backtest_id: str, config: dict) -> dict:
    """Run backtest and persist results."""
    log.info("worker_run_backtest", backtest_id=backtest_id)
    settings = get_settings()

    try:
        import pandas as pd
        from datetime import datetime
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy import text

        engine = create_async_engine(settings.database_url)
        async with AsyncSession(engine) as session:
            rows = await session.execute(text(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol=:sym AND timeframe=:tf AND ts BETWEEN :s AND :e ORDER BY ts"
            ), {
                "sym": config["symbol"], "tf": config["timeframe"],
                "s": config["start_date"], "e": config["end_date"],
            })
            df = pd.DataFrame(rows.fetchall(), columns=["ts","open","high","low","close","volume"])

        if df.empty:
            return {"error": "no data"}
        df.index = pd.to_datetime(df["ts"])

        from app.features.pipeline import compute_features
        from app.backtest.engine import BacktestEngine, BacktestConfig
        from app.ml.supervised import GBMStrategy

        features = compute_features(df)
        model_path = config.get("model_path")
        strategy = GBMStrategy.load(model_path) if model_path else None
        if strategy is None:
            return {"error": "no strategy"}

        bt_config = BacktestConfig(
            strategy_id=config.get("strategy_id", "unknown"),
            symbol=config["symbol"],
            timeframe=config["timeframe"],
            start_date=datetime.fromisoformat(config["start_date"]),
            end_date=datetime.fromisoformat(config["end_date"]),
            initial_capital=float(config.get("initial_capital", 10_000)),
        )
        engine = BacktestEngine(bt_config, strategy, features)
        results = engine.run(df)

        import json
        async with AsyncSession(engine_db := create_async_engine(settings.database_url)) as session:
            await session.execute(text(
                "UPDATE backtest_results SET status='completed', results=:r::jsonb WHERE id=:id"
            ), {"r": json.dumps(results), "id": backtest_id})
            await session.commit()

        log.info("worker_backtest_done", backtest_id=backtest_id)
        return {"backtest_id": backtest_id, "metrics": results.get("metrics", {})}
    except Exception as exc:
        log.error("worker_backtest_error", backtest_id=backtest_id, error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Task: fetch_history
# ---------------------------------------------------------------------------

async def fetch_history(ctx: dict, symbol: str, timeframe: str, since: str, limit: int = 1000) -> dict:
    """Fetch historical OHLCV and persist to DB."""
    log.info("worker_fetch_history", symbol=symbol, timeframe=timeframe)
    settings = get_settings()

    try:
        from app.data.binance import BinanceDataFetcher
        fetcher = BinanceDataFetcher(settings.binance_api_key, settings.binance_api_secret)
        rows = await fetcher.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy import text
        engine = create_async_engine(settings.database_url)
        async with AsyncSession(engine) as session:
            for row in rows:
                await session.execute(text("""
                    INSERT INTO ohlcv (ts, symbol, timeframe, open, high, low, close, volume)
                    VALUES (:ts, :sym, :tf, :o, :h, :l, :c, :v)
                    ON CONFLICT (ts, symbol, timeframe) DO UPDATE
                    SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume
                """), {"ts": row.ts, "sym": symbol, "tf": timeframe,
                       "o": row.open, "h": row.high, "l": row.low,
                       "c": row.close, "v": row.volume})
            await session.commit()

        log.info("worker_fetch_done", symbol=symbol, rows=len(rows))
        return {"symbol": symbol, "rows_fetched": len(rows)}
    except Exception as exc:
        log.error("worker_fetch_error", symbol=symbol, error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# arq WorkerSettings
# ---------------------------------------------------------------------------

def _redis_settings() -> RedisSettings:
    s = get_settings()
    url = s.redis_url or "redis://localhost:6379"
    # arq wants host/port separately
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password or None,
        database=int(parsed.path.lstrip("/") or 0),
    )


class WorkerSettings:
    functions = [train_model, run_backtest, fetch_history]
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 3600        # 1h max per job
    keep_result = 86400       # keep result 24h
    queue_name = "arq:queue"
    health_check_interval = 60
    log_results = True
