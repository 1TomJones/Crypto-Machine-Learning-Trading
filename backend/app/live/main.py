"""Live trading process.

Entry point: python -m app.live.main

Event loop:
  1. Subscribe to Redis trader:cmd channel for start/stop/kill commands
  2. Connect Binance WebSocket for live ticks
  3. Every closed bar: compute features → model.predict() → risk gate → OMS.submit()
  4. Heartbeat to Redis trader:heartbeat every 5s
  5. Reconciliation loop every 60s
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from datetime import datetime, timezone

import ccxt.pro as ccxtpro
import orjson
import structlog

from app.config import get_settings
from app.features.pipeline import compute_features
from app.live.alerter import TelegramAlerter
from app.oms.order import OrderSide, OrderType
from app.oms.oms import OMS
from app.risk.gate import RiskGate, RiskLimits
from app.risk.kill_switch import KillSwitch

log = structlog.get_logger(__name__)

HEARTBEAT_KEY = "trader:heartbeat"
HEARTBEAT_TTL = 30
CMD_CHANNEL = "trader:cmd"
TICK_CHANNEL = "trader:ticks"


class LiveTrader:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
        )
        self._running = False
        self._state: dict = {"trading_enabled": True}
        self._bar_buffer: list[dict] = []   # accumulate OHLCV rows
        self._exchange = None
        self._redis = None
        self._oms: OMS | None = None
        self._kill_switch: KillSwitch | None = None
        self._model = None
        self._equity = float(self.settings.initial_capital or 10_000)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self.settings.redis_url, decode_responses=True)

        self._exchange = ccxtpro.binance({
            "apiKey":  self.settings.binance_api_key,
            "secret":  self.settings.binance_api_secret,
            "options": {"defaultType": "spot"},
        })

        limits = RiskLimits(
            max_daily_loss_pct=float(self.settings.max_daily_loss_pct or 0.03),
            max_drawdown_pct=float(self.settings.max_drawdown_pct or 0.10),
        )
        risk_gate = RiskGate(limits)

        self._oms = OMS(
            exchange=self._exchange,
            risk_gate=risk_gate,
            alerter=self.alerter,
            db_session_factory=None,
            portfolio_equity_fn=self._get_equity,
        )
        self._kill_switch = KillSwitch(
            exchange=self._exchange,
            alerter=self.alerter,
            state_store=self._state,
            redis_client=self._redis,
        )

        await self._load_champion_model()
        self._running = True

        await self.alerter.info("Live trader starting…")
        log.info("live_trader_start")

        await asyncio.gather(
            self._heartbeat_loop(),
            self._cmd_listener(),
            self._market_data_loop(),
            self._reconcile_loop(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._exchange:
            await self._exchange.close()
        log.info("live_trader_stopped")
        await self.alerter.info("Live trader stopped.")

    # ------------------------------------------------------------------
    # Core loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                payload = orjson.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "trading_enabled": self._state.get("trading_enabled", False),
                    "equity": self._equity,
                }).decode()
                await self._redis.set(HEARTBEAT_KEY, payload, ex=HEARTBEAT_TTL)
            except Exception as exc:
                log.error("heartbeat_error", error=str(exc))
            await asyncio.sleep(5)

    async def _cmd_listener(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CMD_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                cmd = orjson.loads(message["data"])
            except Exception:
                continue
            action = cmd.get("action", "")
            log.info("cmd_received", action=action)
            if action == "stop":
                await self.stop()
                return
            elif action == "kill":
                reason = cmd.get("reason", "Manual kill via API")
                await self._kill_switch.trigger(reason)
                self._running = False
                return
            elif action == "start":
                self._state["trading_enabled"] = True
            elif action == "pause":
                self._state["trading_enabled"] = False

    async def _market_data_loop(self) -> None:
        symbol = self.settings.trading_symbol or "BTC/USDT"
        timeframe = self.settings.trading_timeframe or "1m"
        while self._running:
            try:
                ohlcv = await self._exchange.watch_ohlcv(symbol, timeframe)
                for bar in ohlcv:
                    ts, o, h, l, c, v = bar
                    self._bar_buffer.append({
                        "ts": ts, "open": o, "high": h,
                        "low": l, "close": c, "volume": v,
                    })
                    # Publish tick
                    await self._redis.publish(
                        TICK_CHANNEL,
                        orjson.dumps({"symbol": symbol, "close": c, "ts": ts}).decode(),
                    )
                if len(self._bar_buffer) >= 500:
                    await self._on_bar_closed(symbol, self._bar_buffer[-1])
            except Exception as exc:
                log.error("market_data_error", error=str(exc))
                await asyncio.sleep(5)

    async def _reconcile_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)
            try:
                if self._oms:
                    await self._oms.reconcile()
            except Exception as exc:
                log.error("reconcile_loop_error", error=str(exc))

    # ------------------------------------------------------------------
    # Signal → order flow
    # ------------------------------------------------------------------

    async def _on_bar_closed(self, symbol: str, bar: dict) -> None:
        if not self._state.get("trading_enabled") or self._model is None:
            return
        try:
            import pandas as pd
            df = pd.DataFrame(self._bar_buffer[-500:])
            df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
            features = compute_features(df)
            signal = self._model.predict(features)
            if signal is None:
                return

            side = OrderSide.BUY if signal.target_weight > 0 else OrderSide.SELL
            qty = abs(signal.target_weight) * self._equity / bar["close"]
            if qty < 1e-6:
                return

            await self._oms.submit(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                qty=qty,
                signal=signal,
            )
            # Update risk gate equity
            self._oms.risk_gate.update_equity(self._equity)
        except Exception as exc:
            log.error("on_bar_error", error=str(exc))

    async def _get_equity(self) -> float:
        try:
            balance = await asyncio.wait_for(
                self._exchange.fetch_balance(), timeout=10.0
            )
            usdt = float(balance.get("USDT", {}).get("total", self._equity))
            self._equity = usdt
            return usdt
        except Exception:
            return self._equity

    async def _load_champion_model(self) -> None:
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy import text
            engine = create_async_engine(self.settings.database_url, echo=False)
            async with AsyncSession(engine) as session:
                result = await session.execute(
                    text("SELECT artifact_path, strategy_type FROM model_artifacts WHERE is_champion = TRUE LIMIT 1")
                )
                row = result.fetchone()
                if row is None:
                    log.warning("no_champion_model")
                    return
                path, stype = row
                if stype in ("lightgbm", "xgboost", "random_forest", "logistic"):
                    from app.ml.supervised import GBMStrategy
                    self._model = GBMStrategy.load(path)
                elif stype == "lstm":
                    from app.ml.deep_learning import LSTMStrategy
                    self._model = LSTMStrategy.load(path)
                elif stype in ("ppo", "sac", "a2c"):
                    from app.ml.rl import RLStrategy
                    self._model = RLStrategy.load(path)
                log.info("champion_model_loaded", path=path, type=stype)
        except Exception as exc:
            log.error("load_model_error", error=str(exc))


# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------

async def main() -> None:
    trader = LiveTrader()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(trader.stop()))

    await trader.start()


if __name__ == "__main__":
    asyncio.run(main())
