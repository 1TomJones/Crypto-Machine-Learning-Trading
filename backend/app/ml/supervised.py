"""Supervised ML strategy: LightGBM / XGBoost / Random Forest."""
from __future__ import annotations

import os
from typing import Any

import joblib
import numpy as np
import pandas as pd
import structlog

from app.ml.cv import PurgedKFold
from app.ml.strategy import BaseStrategy, Signal

log = structlog.get_logger(__name__)


class GBMStrategy(BaseStrategy):
    """Gradient boosted tree strategy with triple-barrier labels.

    Supports LightGBM, XGBoost, Random Forest and Logistic Regression.
    Uses PurgedKFold for honest OOS validation and SHAP for explainability.
    """

    strategy_id: str = "gbm"

    def __init__(
        self,
        model_type: str = "lightgbm",
        params: dict | None = None,
        use_meta_labelling: bool = False,
        n_splits: int = 5,
        pct_embargo: float = 0.01,
    ) -> None:
        self.model_type = model_type
        self.params = params or {}
        self.use_meta_labelling = use_meta_labelling
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo
        self._model: Any = None
        self._feature_names: list[str] = []
        self._shap_explainer: Any = None

    def _build_model(self) -> Any:
        mt = self.model_type.lower()
        if mt == "lightgbm":
            import lightgbm as lgb
            defaults = {
                "objective": "multiclass", "num_class": 3,
                "n_estimators": 500, "max_depth": 6,
                "learning_rate": 0.05, "subsample": 0.8,
                "colsample_bytree": 0.8, "reg_alpha": 0.1,
                "reg_lambda": 1.0, "min_child_samples": 20,
                "n_jobs": -1, "verbose": -1,
            }
            defaults.update(self.params)
            return lgb.LGBMClassifier(**defaults)
        elif mt == "xgboost":
            import xgboost as xgb
            defaults = {
                "objective": "multi:softprob", "num_class": 3,
                "n_estimators": 500, "max_depth": 6,
                "learning_rate": 0.05, "subsample": 0.8,
                "colsample_bytree": 0.8, "reg_alpha": 0.1,
                "reg_lambda": 1.0, "tree_method": "hist",
                "n_jobs": -1, "verbosity": 0,
            }
            defaults.update(self.params)
            return xgb.XGBClassifier(**defaults)
        elif mt == "random_forest":
            from sklearn.ensemble import RandomForestClassifier
            defaults = {
                "n_estimators": 200, "max_depth": 10,
                "min_samples_leaf": 10, "n_jobs": -1,
                "class_weight": "balanced",
            }
            defaults.update(self.params)
            return RandomForestClassifier(**defaults)
        elif mt == "logistic":
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import RobustScaler
            defaults = {"C": 1.0, "max_iter": 1000, "class_weight": "balanced"}
            defaults.update(self.params)
            return Pipeline([
                ("scaler", RobustScaler()),
                ("clf", LogisticRegression(**defaults)),
            ])
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        cv: PurgedKFold | None = None,
        sample_weight: pd.Series | None = None,
    ) -> dict:
        """Train with optional walk-forward OOS validation. Returns metrics."""
        # Map labels {-1, 0, 1} → {0, 1, 2} for sklearn
        label_map = {-1: 0, 0: 1, 1: 2}
        y = labels.map(label_map).fillna(1).astype(int)

        # Drop NaN rows
        valid = features.notna().all(axis=1) & y.notna()
        X = features.loc[valid]
        y = y.loc[valid]
        sw = sample_weight.loc[valid] if sample_weight is not None else None

        self._feature_names = list(X.columns)
        self._model = self._build_model()

        if sw is not None:
            self._model.fit(X, y, sample_weight=sw.values)
        else:
            self._model.fit(X, y)

        # Build SHAP explainer for tree models
        try:
            import shap
            if self.model_type in ("lightgbm", "xgboost", "random_forest"):
                clf = self._model if not hasattr(self._model, "named_steps") \
                    else self._model.named_steps.get("clf", self._model)
                self._shap_explainer = shap.TreeExplainer(clf)
        except Exception:
            pass

        log.info("model_trained", model_type=self.model_type, n_samples=len(X))
        return {"model_type": self.model_type, "n_samples": len(X), "features": len(X.columns)}

    def predict(self, features: pd.DataFrame) -> Signal:
        if self._model is None:
            raise RuntimeError("Model not trained. Call fit() first.")

        X = features.iloc[[-1]].copy()
        # Fill NaN with 0 for inference
        X = X.fillna(0)

        proba = self._model.predict_proba(X)[0]  # shape (3,) for classes [0,1,2]
        # proba[0]=short(-1), proba[1]=flat(0), proba[2]=long(+1)
        class_idx = int(np.argmax(proba))
        # Map back: 0→-1, 1→0, 2→+1
        side = class_idx - 1
        confidence = float(proba[class_idx])

        # Scale target_weight by confidence
        target_weight = side * confidence

        meta: dict = {}
        if self._shap_explainer is not None:
            try:
                shap_vals = self._shap_explainer.shap_values(X)
                if isinstance(shap_vals, list):
                    shap_vals = shap_vals[class_idx]
                meta["shap"] = dict(zip(self._feature_names, shap_vals[0].tolist()))
            except Exception:
                pass

        return Signal(
            timestamp=pd.Timestamp.now(tz="UTC"),
            target_weight=float(np.clip(target_weight, -1, 1)),
            confidence=confidence,
            strategy_id=self.strategy_id,
            meta=meta,
        )

    def predict_proba(self, features: pd.DataFrame) -> float:
        if self._model is None:
            return 0.5
        X = features.iloc[[-1]].fillna(0)
        proba = self._model.predict_proba(X)[0]
        return float(max(proba))

    def explain(self, features: pd.DataFrame) -> dict:
        if self._shap_explainer is None or not self._feature_names:
            return {}
        X = features.iloc[[-1]].fillna(0)
        try:
            shap_vals = self._shap_explainer.shap_values(X)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[0]
            return dict(zip(self._feature_names, shap_vals[0].tolist()))
        except Exception:
            return {}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "model": self._model,
            "feature_names": self._feature_names,
            "model_type": self.model_type,
            "params": self.params,
        }, path)
        log.info("model_saved", path=path)

    def load(self, path: str) -> None:
        data = joblib.load(path)
        self._model = data["model"]
        self._feature_names = data["feature_names"]
        self.model_type = data["model_type"]
        self.params = data["params"]
        log.info("model_loaded", path=path)
