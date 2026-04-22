"""Reinforcement learning: Gymnasium environment and PPO strategy."""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd
import structlog

from app.ml.strategy import BaseStrategy, Signal

log = structlog.get_logger(__name__)


class CryptoTradingEnv:
    """Gymnasium-compatible environment for BTC/USD trading.

    State: price features + current_position + unrealized_pnl + hour_sin + hour_cos
    Actions: 0=short, 1=flat, 2=long  (mapped to -1, 0, +1)
    Reward: differential Sharpe ratio minus transaction costs
    """

    def __init__(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        initial_capital: float = 10_000.0,
        taker_fee: float = 0.004,
        maker_fee: float = 0.0025,
        max_episode_steps: int = 1440,
        reward_type: str = "differential_sharpe",
    ) -> None:
        try:
            import gymnasium as gym
            self._gym = gym
        except ImportError:
            raise ImportError("gymnasium required. pip install gymnasium")

        self.features = features.fillna(0).values.astype(np.float32)
        self.close = close.values.astype(np.float64)
        self.initial_capital = initial_capital
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.max_episode_steps = max_episode_steps
        self.reward_type = reward_type

        n_feat = self.features.shape[1]
        obs_dim = n_feat + 4  # + position, unrealized_pnl, hour_sin, hour_cos
        import gymnasium.spaces as spaces
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)

        # Differential Sharpe state
        self._A = 0.0  # running mean of returns
        self._B = 0.0  # running mean of squared returns
        self._eta = 0.01  # learning rate for dS

        self._step = 0
        self._position = 0  # -1, 0, +1
        self._entry_price = 0.0
        self._equity = initial_capital
        self._start_idx = 0

    def reset(self, seed=None, options=None):
        self._step = 0
        self._position = 0
        self._entry_price = 0.0
        self._equity = self.initial_capital
        self._A = 0.0
        self._B = 0.0
        self._start_idx = max(0, len(self.features) - self.max_episode_steps)
        return self._get_obs(), {}

    def step(self, action: int):
        idx = self._start_idx + self._step
        if idx >= len(self.close) - 1:
            return self._get_obs(), 0.0, True, False, {}

        current_price = self.close[idx]
        next_price = self.close[min(idx + 1, len(self.close) - 1)]
        new_position = action - 1  # 0→-1, 1→0, 2→+1

        # Transaction cost on position change
        trade_cost = 0.0
        if new_position != self._position:
            trade_cost = abs(new_position - self._position) * self.taker_fee
            self._position = new_position
            self._entry_price = current_price

        # P&L for this step
        price_return = (next_price - current_price) / (current_price + 1e-10)
        step_return = self._position * price_return - trade_cost

        # Reward
        if self.reward_type == "differential_sharpe":
            reward = self._differential_sharpe(step_return)
        else:
            reward = step_return

        self._equity *= (1 + step_return)
        self._step += 1

        terminated = self._step >= self.max_episode_steps or self._equity < self.initial_capital * 0.5
        return self._get_obs(), float(reward), terminated, False, {
            "step_return": step_return, "equity": self._equity
        }

    def _differential_sharpe(self, r_t: float) -> float:
        """Moody & Saffell 1998 differential Sharpe reward."""
        delta_A = r_t - self._A
        delta_B = r_t ** 2 - self._B
        denom = (self._B - self._A ** 2) ** 1.5 + 1e-10
        reward = (self._B * delta_A - 0.5 * self._A * delta_B) / denom
        self._A += self._eta * delta_A
        self._B += self._eta * delta_B
        return float(reward)

    def _get_obs(self) -> np.ndarray:
        idx = min(self._start_idx + self._step, len(self.features) - 1)
        feat = self.features[idx]
        current_price = self.close[idx]
        unrealized_pnl = 0.0
        if self._position != 0 and self._entry_price > 0:
            unrealized_pnl = self._position * (current_price - self._entry_price) / self._entry_price

        hour = (idx % 1440) / 1440.0 * 2 * np.pi
        extra = np.array([
            float(self._position),
            float(np.clip(unrealized_pnl, -1, 1)),
            float(np.sin(hour)),
            float(np.cos(hour)),
        ], dtype=np.float32)
        return np.concatenate([feat, extra])


class RLStrategy(BaseStrategy):
    """PPO reinforcement learning strategy via Stable-Baselines3."""

    strategy_id: str = "ppo"

    def __init__(
        self,
        algorithm: str = "PPO",
        policy: str = "MlpPolicy",
        total_timesteps: int = 500_000,
        learning_rate: float = 3e-4,
        reward_type: str = "differential_sharpe",
    ) -> None:
        self.algorithm = algorithm
        self.policy = policy
        self.total_timesteps = total_timesteps
        self.learning_rate = learning_rate
        self.reward_type = reward_type
        self._model: Any = None
        self._env: CryptoTradingEnv | None = None

    def fit(
        self,
        features: pd.DataFrame,
        labels: pd.Series | None = None,
        cv=None,
        sample_weight=None,
    ) -> dict:
        try:
            from stable_baselines3 import PPO, SAC, A2C
        except ImportError:
            raise ImportError("stable-baselines3 required. pip install stable-baselines3")

        close = features.index.map(lambda i: 1.0)  # fallback
        self._env = CryptoTradingEnv(
            features=features,
            close=pd.Series(np.ones(len(features))),
            reward_type=self.reward_type,
        )

        algo_cls = {"PPO": PPO, "SAC": SAC, "A2C": A2C}.get(self.algorithm, PPO)
        self._model = algo_cls(
            self.policy, self._env,
            learning_rate=self.learning_rate,
            verbose=0,
        )
        self._model.learn(total_timesteps=self.total_timesteps)
        log.info("rl_trained", algorithm=self.algorithm, timesteps=self.total_timesteps)
        return {"algorithm": self.algorithm, "timesteps": self.total_timesteps}

    def predict(self, features: pd.DataFrame) -> Signal:
        if self._model is None:
            return Signal(timestamp=pd.Timestamp.now(tz="UTC"), target_weight=0.0)

        obs = features.iloc[-1].fillna(0).values.astype(np.float32)
        extra = np.zeros(4, dtype=np.float32)
        obs_full = np.concatenate([obs, extra])

        action, _ = self._model.predict(obs_full, deterministic=True)
        side = int(action) - 1
        return Signal(
            timestamp=pd.Timestamp.now(tz="UTC"),
            target_weight=float(side),
            confidence=1.0,
            strategy_id=self.strategy_id,
        )

    def predict_proba(self, features: pd.DataFrame) -> float:
        return 1.0

    def save(self, path: str) -> None:
        if self._model:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._model.save(path)

    def load(self, path: str) -> None:
        try:
            from stable_baselines3 import PPO
            self._model = PPO.load(path)
        except Exception as e:
            log.error("rl_load_error", error=str(e))
