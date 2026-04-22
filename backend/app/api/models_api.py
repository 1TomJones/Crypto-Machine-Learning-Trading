"""Model registry and training router."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import ModelArtifact, Strategy, User

router = APIRouter()


class TrainRequest(BaseModel):
    strategy_id: uuid.UUID
    config: dict = {}
    optuna_trials: int = 50


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
    return model


@router.post("/train")
async def train_model(
    body: TrainRequest,
    _user: User = Depends(get_current_user),
):
    """Queue a training job."""
    import arq
    from app.config import get_settings
    settings = get_settings()
    pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.redis_url))
    job = await pool.enqueue_job(
        "train_model",
        strategy_id=str(body.strategy_id),
        config=body.config,
        optuna_trials=body.optuna_trials,
    )
    await pool.aclose()
    return {"job_id": job.job_id, "status": "queued"}


@router.post("/{model_id}/deploy")
async def deploy_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Set this model as champion for its strategy."""
    result = await db.execute(select(ModelArtifact).where(ModelArtifact.id == model_id))
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # Demote existing champion
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


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, _user: User = Depends(get_current_user)):
    """Check arq job status."""
    import arq
    from app.config import get_settings
    settings = get_settings()
    pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.redis_url))
    job = arq.jobs.Job(job_id=job_id, redis=pool)
    info = await job.info()
    await pool.aclose()
    if info is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": info.status.value if info.status else "unknown",
        "result": info.result,
        "enqueue_time": info.enqueue_time.isoformat() if info.enqueue_time else None,
    }
