# Crypto ML Trading — Operations Runbook

## Pre-Flight Checklist (before enabling live trading)

- [ ] DB migrations applied: `alembic upgrade head`
- [ ] Risk settings reviewed at `/risk` — daily loss ≤3%, drawdown ≤10%
- [ ] Champion model deployed and back-tested (Sharpe > 0.5, PSR > 0.8)
- [ ] Telegram bot token and chat ID set in `.env` and smoke-tested
- [ ] Exchange API keys set with **trade only** permission (never withdraw)
- [ ] Symbol whitelist contains only intended pairs
- [ ] Redis running: `redis-cli ping` → PONG
- [ ] TimescaleDB running, hypertable created, recent data loaded
- [ ] `docker compose up -d` — all containers healthy
- [ ] `/health` returns `{"status": "ok"}`, `/health/trader` returns age < 10s

---

## Starting the System

```bash
# 1. Start infrastructure
docker compose up -d postgres redis

# 2. Apply migrations
cd backend && alembic upgrade head

# 3. Start backend API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. Start arq workers
arq app.workers.settings.WorkerSettings

# 5. Start live trader
python -m app.live.main

# 6. Verify heartbeat
curl http://localhost:8000/health/trader
```

---

## Kill Switch

### Via UI
Navigate to **Live Trading** → **Kill Switch** button → confirm with reason.

### Via Telegram
Send `/kill <reason>` to the bot.

### Via CLI
```bash
python -m app.risk.kill_switch trigger "manual kill — reason here"
```

### What happens
1. `trading_enabled = False` persisted to Redis
2. Telegram alert: `KILL SWITCH: <reason>`
3. `cancel_all_orders()` — all open orders cancelled (10s timeout)
4. `fetch_positions()` — all open positions fetched
5. Each position: market order with `reduceOnly=True`, 3 retries, 2^n backoff
6. State persisted to Redis key `trader:state` (TTL 24h)
7. Telegram alert: `KILL COMPLETE — MANUAL RESTART REQUIRED`

**To restart:** fix root cause → manually call `POST /live/start` after review.

---

## Reconciliation Failures

The OMS reconciliation loop runs every 60s comparing local order state to exchange.

### Symptom: `oms_reconcile_missing` in logs
Order exists locally but not on exchange.
- Check if order was filled or cancelled on the exchange
- Verify the `exchange_order_id` field for the order
- If exchange shows filled: update local state via the sync endpoint

### Symptom: `oms_reconcile_error` with timeout
- Check exchange API status: `status.binance.com`
- Verify API keys are valid (not expired or rate-limited)
- Check network connectivity from the trading host

---

## NaN / Stale Data

### Symptom: `kill_switch_triggered` with reason containing "NaN model output"
The model returned NaN. Root causes:
- Feature pipeline received a bar with missing OHLCV
- Model artifact is corrupted or trained on different feature set

Fix:
1. Verify latest bars in DB: `SELECT * FROM ohlcv_bars ORDER BY ts DESC LIMIT 5`
2. Re-run data quality check: `POST /api/data/quality`
3. Retrain model if features have changed: **Model Builder** page
4. Restart trader after deploying new champion

### Symptom: `kill_switch_triggered` with reason "stale data feed"
WebSocket disconnected and fallback Kraken feed also failed.
1. Check Binance WS status
2. Restart live trader process (`docker compose restart live-trader`)

---

## Risk Limit Breaches

### Max Daily Loss
Triggered in `RiskGate.check()` when `daily_pnl / start_of_day_equity < -max_daily_loss_pct`.
- Trading auto-halted (not a full kill — positions kept open)
- Review market conditions
- If deliberate drawdown: `PATCH /api/risk/settings` to adjust limit or `POST /live/start` to re-enable after review

### Max Drawdown
Same as above but using peak equity. This is more severe:
- Indicates strategy regime change
- Consider deploying a defensive model (small position sizes) or flat
- Full kill switch if drawdown continues

---

## Exchange API 4xx Loop

If `create_order` / `fetch_positions` returns repeated 4xx:
- **401**: API key expired → rotate keys, update `.env`, restart
- **403**: IP not whitelisted → update exchange IP whitelist
- **429**: Rate limited → back off; arq workers throttle automatically
- **400 with "insufficient balance"**: Equity model mismatch → reconcile equity

After any 4xx recovery, run full reconciliation:
```bash
curl -X POST http://localhost:8000/api/live/reconcile \
  -H "Authorization: Bearer $TOKEN"
```

---

## Database Maintenance

### Compress old chunks (TimescaleDB)
```sql
SELECT add_compression_policy('ohlcv_bars', INTERVAL '7 days');
```

### Refresh continuous aggregates
```sql
CALL refresh_continuous_aggregate('ohlcv_1h', NULL, NULL);
```

### Drop old data
```sql
SELECT drop_chunks('ohlcv_bars', INTERVAL '2 years');
```

---

## Monitoring Checklist (daily)

- [ ] Check `/health/trader` — heartbeat age < 30s
- [ ] Review Telegram for any critical alerts overnight
- [ ] Check daily PnL in Dashboard
- [ ] Verify position reconciliation matches exchange UI
- [ ] Review `audit_log` table for unexpected actions
- [ ] Check arq worker queue depth: `redis-cli llen arq:queue`
