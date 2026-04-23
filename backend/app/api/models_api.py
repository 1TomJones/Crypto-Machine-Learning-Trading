"""Model registry and training router."""
from __future__ import annotations

import asyncio
import os
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import ModelArtifact, User

log = structlog.get_logger(__name__)
router = APIRouter()


class TrainRequest(BaseModel):
    strategy_id: uuid.UUID
    config: dict = {}
    optuna_trials: int = 0


@router.get("")
async def list_models(
    strategy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(ModelArtifact).order_by(ModelArtifact.created_at.desc())
    if strategy_id:
        q = q.where(ModelArtifact.strategy_id == strategy_id)
    result = await db.execute(q)
    models = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "strategy_id": str(m.strategy_id),
            "model_type": m.model_type,
            "feature_set_version": m.feature_set_version,
            "metrics": m.metrics,
            "is_champion": m.is_champion,
            "artifact_path": m.artifact_path,
            "created_at": m.created_at.isoformat(),
        }
        for m in models
    ]


@router.get("/{model_id}")
async def get_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(ModelArtifact).where(ModelArtifact.id == model_id))
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {
        "id": str(model.id),
        "strategy_id": str(model.strategy_id),
        "model_type": model.model_type,
        "metrics": model.metrics,
        "is_champion": model.is_champion,
        "artifact_path": model.artifact_path,
        "created_at": model.created_at.isoformat(),
    }


@router.post("/train")
async def train_model(
    body: TrainRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Create model record and kick off background training."""
    model_type = body.config.get("model_type", "lightgbm")
    model = ModelArtifact(
        strategy_id=body.strategy_id,
        model_type=model_type,
        metrics={"status": "training", "progress": "Starting…"},
        artifact_path="",
    )
    db.add(model)
    await db.flush()
    await db.refresh(model)
    model_id = str(model.id)
    background_tasks.add_task(
        _run_training_bg, model_id, str(body.strategy_id), dict(body.config)
    )
    return {"model_id": model_id, "status": "training"}


@router.post("/{model_id}/deploy")
async def deploy_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(ModelArtifact).where(ModelArtifact.id == model_id))
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.artifact_path:
        raise HTTPException(status_code=400, detail="Model is not yet trained")

    existing = await db.execute(
        select(ModelArtifact).where(
            ModelArtifact.strategy_id == model.strategy_id,
            ModelArtifact.is_champion == True,  # noqa: E712
        )
    )
    for old in existing.scalars().all():
        old.is_champion = False

    model.is_champion = True
    await db.flush()
    return {"message": f"Model {model_id} deployed as champion"}


# ---------------------------------------------------------------------------
# Background training
# ---------------------------------------------------------------------------

async def _run_training_bg(model_id: str, strategy_id: str, config: dict) -> None:
    """Run ML training in the background and update the ModelArtifact record."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.config import get_settings
    from app.db_models import ModelArtifact, OHLCVBar
    from sqlalchemy import select

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _update_metrics(m: dict) -> None:
        async with factory() as s:
            r = await s.execute(select(ModelArtifact).where(ModelArtifact.id == model_id))
            rec = r.scalar_one_or_none()
            if rec:
                rec.metrics = m
                if m.get("artifact_path"):
                    rec.artifact_path = m["artifact_path"]
                await s.commit()

    try:
        import pandas as pd
        import numpy as np

        symbol = config.get("symbol", "BTC/USDT")
        model_type = config.get("model_type", "lightgbm")

        await _update_metrics({"status": "training", "progress": "Loading data…"})

        # Load all available OHLCV for this symbol
        async with factory() as s:
            q = (
                select(OHLCVBar)
                .where(OHLCVBar.symbol == symbol, OHLCVBar.exchange == "binance")
                .order_by(OHLCVBar.ts)
                .limit(10000)
            )
            result = await s.execute(q)
            bars = result.scalars().all()

        if not bars:
            raise ValueError(
                f"No OHLCV data for {symbol}. Go to Markets and click 'Fetch Latest' first."
            )

        df = pd.DataFrame(
            [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low,
              "close": b.close, "volume": b.volume} for b in bars]
        ).set_index("ts").sort_index()

        await _update_metrics({"status": "training", "progress": f"Computing features on {len(df)} bars…"})

        # Features
        from app.features.pipeline import compute_features
        features = await asyncio.get_event_loop().run_in_executor(
            None, compute_features, df
        )

        # Simple labels: 5-bar forward return threshold
        fwd = df["close"].pct_change(5).shift(-5)
        threshold = fwd.std() * 0.5
        y = pd.Series(1, index=fwd.index)  # 1=neutral
        y[fwd > threshold] = 2             # 2=up
        y[fwd < -threshold] = 0            # 0=down

        valid_idx = features.dropna().index.intersection(y.dropna().index)
        X = features.loc[valid_idx].astype(float)
        y = y.loc[valid_idx]

        if len(X) < 60:
            raise ValueError(
                f"Only {len(X)} usable samples after feature warm-up. "
                "Fetch more data (use 1h timeframe and fetch 1000 candles)."
            )

        await _update_metrics({
            "status": "training",
            "progress": f"Training {model_type} on {len(X)} samples…",
        })

        split = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]

        # Train using GBMStrategy (runs in thread to avoid blocking event loop)
        from app.ml.supervised import GBMStrategy

        strategy = GBMStrategy(model_type=model_type)

        def _fit():
            strategy.fit(X_train, y_train)
            preds = strategy._model.predict(X_test)
            acc = float((preds == y_test.values).mean())
            return acc

        accuracy = await asyncio.get_event_loop().run_in_executor(None, _fit)

        # Save artifact
        artifact_dir = getattr(settings, "model_artifact_path", None) or "/tmp/models"
        os.makedirs(artifact_dir, exist_ok=True)
        path = os.path.join(artifact_dir, f"{strategy_id}_{model_id}.pkl")
        strategy.save(path)

        final_metrics = {
            "status": "completed",
            "accuracy": round(accuracy, 4),
            "n_samples": len(X),
            "n_features": int(X.shape[1]),
            "symbol": symbol,
            "model_type": model_type,
            "artifact_path": path,
        }
        await _update_metrics(final_metrics)
        log.info("training_completed", model_id=model_id, accuracy=accuracy)

    except Exception as exc:
        log.error("training_failed", model_id=model_id, error=str(exc))
        await _update_metrics({"status": "failed", "error": str(exc)})
    finally:
        await engine.dispose()
