"""LSTM deep learning strategy for time-series prediction."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import structlog

from app.ml.strategy import BaseStrategy, Signal

log = structlog.get_logger(__name__)


class LSTMModel:
    """PyTorch LSTM classifier wrapping the raw nn.Module."""

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
        num_classes: int = 3,
    ) -> None:
        try:
            import torch
            import torch.nn as nn

            class _Net(nn.Module):
                def __init__(self):
                    super().__init__()
                    self.lstm = nn.LSTM(
                        input_size, hidden_size, num_layers,
                        batch_first=True, dropout=dropout if num_layers > 1 else 0.0,
                    )
                    self.drop = nn.Dropout(dropout)
                    self.fc = nn.Linear(hidden_size, num_classes)

                def forward(self, x):
                    out, _ = self.lstm(x)
                    out = self.drop(out[:, -1, :])
                    return self.fc(out)

            self._torch = torch
            self._nn = nn
            self.net = _Net()
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.net.to(self.device)
        except ImportError as e:
            raise ImportError("PyTorch required for LSTMModel") from e

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int = 50,
        batch_size: int = 128,
        lr: float = 1e-3,
        val_split: float = 0.1,
    ) -> list[float]:
        """Train the LSTM. Returns list of validation losses."""
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        X_t = torch.FloatTensor(X).to(self.device)
        y_t = torch.LongTensor(y).to(self.device)

        n_val = max(1, int(len(X) * val_split))
        X_train, X_val = X_t[:-n_val], X_t[-n_val:]
        y_train, y_val = y_t[:-n_val], y_t[-n_val:]

        dataset = TensorDataset(X_train, y_train)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

        optimizer = torch.optim.Adam(self.net.parameters(), lr=lr, weight_decay=1e-4)
        criterion = torch.nn.CrossEntropyLoss()
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5)

        val_losses = []
        best_loss = float("inf")
        patience_counter = 0
        patience = 10

        for epoch in range(epochs):
            self.net.train()
            for xb, yb in loader:
                optimizer.zero_grad()
                pred = self.net(xb)
                loss = criterion(pred, yb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                optimizer.step()

            self.net.eval()
            with torch.no_grad():
                val_pred = self.net(X_val)
                val_loss = criterion(val_pred, y_val).item()
            val_losses.append(val_loss)
            scheduler.step(val_loss)

            if val_loss < best_loss:
                best_loss = val_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    log.info("lstm_early_stop", epoch=epoch, val_loss=val_loss)
                    break

        return val_losses

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        import torch
        self.net.eval()
        with torch.no_grad():
            X_t = torch.FloatTensor(X).to(self.device)
            logits = self.net(X_t)
            proba = torch.softmax(logits, dim=-1).cpu().numpy()
        return proba

    def save(self, path: str) -> None:
        import torch
        torch.save(self.net.state_dict(), path)

    def load(self, path: str) -> None:
        import torch
        self.net.load_state_dict(torch.load(path, map_location=self.device))


class LSTMStrategy(BaseStrategy):
    """LSTM-based trading strategy."""

    strategy_id: str = "lstm"

    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.1,
        lookback: int = 64,
        epochs: int = 50,
        lr: float = 1e-3,
        batch_size: int = 128,
    ) -> None:
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.lookback = lookback
        self.epochs = epochs
        self.lr = lr
        self.batch_size = batch_size
        self._model: LSTMModel | None = None
        self._feature_names: list[str] = []

    def _make_sequences(
        self, features: pd.DataFrame, labels: pd.Series | None = None
    ) -> tuple[np.ndarray, np.ndarray | None]:
        """Convert flat features to (N, lookback, features) sequences."""
        valid = features.notna().all(axis=1)
        feat = features.loc[valid].values.astype(np.float32)
        lbl = labels.loc[valid].values if labels is not None else None

        # Normalize (RobustScaler per-feature)
        from sklearn.preprocessing import RobustScaler
        scaler = RobustScaler()
        feat = scaler.fit_transform(feat)
        self._scaler = scaler

        X_seqs, y_seqs = [], []
        for i in range(self.lookback, len(feat)):
            X_seqs.append(feat[i - self.lookback: i])
            if lbl is not None:
                y_seqs.append(lbl[i])

        X = np.array(X_seqs, dtype=np.float32)
        y = np.array(y_seqs, dtype=np.int64) if y_seqs else None
        return X, y

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        cv=None,
        sample_weight=None,
    ) -> dict:
        label_map = {-1: 0, 0: 1, 1: 2}
        y_mapped = labels.map(label_map).fillna(1)
        X, y = self._make_sequences(features, y_mapped)

        if len(X) == 0:
            raise ValueError("Not enough data for LSTM sequences")

        self._feature_names = list(features.columns)
        self._model = LSTMModel(
            input_size=features.shape[1],
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        val_losses = self._model.fit(X, y, self.epochs, self.batch_size, self.lr)
        log.info("lstm_trained", n_seqs=len(X), final_val_loss=val_losses[-1] if val_losses else None)
        return {"model_type": "lstm", "n_sequences": len(X), "val_losses": val_losses}

    def predict(self, features: pd.DataFrame) -> Signal:
        if self._model is None:
            raise RuntimeError("Call fit() first")

        # Use last `lookback` rows
        if len(features) < self.lookback:
            return Signal(timestamp=pd.Timestamp.now(tz="UTC"), target_weight=0.0)

        window = features.iloc[-self.lookback:].fillna(0).values.astype(np.float32)
        if hasattr(self, "_scaler"):
            window = self._scaler.transform(window)

        X = window[np.newaxis, :, :]  # shape (1, lookback, features)
        proba = self._model.predict_proba(X)[0]

        class_idx = int(np.argmax(proba))
        side = class_idx - 1
        confidence = float(proba[class_idx])
        target_weight = float(np.clip(side * confidence, -1, 1))

        return Signal(
            timestamp=pd.Timestamp.now(tz="UTC"),
            target_weight=target_weight,
            confidence=confidence,
            strategy_id=self.strategy_id,
        )

    def predict_proba(self, features: pd.DataFrame) -> float:
        sig = self.predict(features)
        return sig.confidence

    def save(self, path: str) -> None:
        import torch
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save({
            "state_dict": self._model.net.state_dict() if self._model else None,
            "config": {
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "dropout": self.dropout,
                "lookback": self.lookback,
                "input_size": len(self._feature_names),
            },
            "feature_names": self._feature_names,
        }, path)

    def load(self, path: str) -> None:
        import torch
        data = torch.load(path, map_location="cpu")
        cfg = data["config"]
        self._feature_names = data["feature_names"]
        self._model = LSTMModel(
            input_size=cfg["input_size"],
            hidden_size=cfg["hidden_size"],
            num_layers=cfg["num_layers"],
            dropout=cfg["dropout"],
        )
        if data["state_dict"]:
            self._model.net.load_state_dict(data["state_dict"])
