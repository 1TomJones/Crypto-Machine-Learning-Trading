import { useAuthStore } from "./store";

const BASE = "/api";

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    useAuthStore.getState().logout();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  // OHLCV
  ohlcv: (symbol: string, timeframe: string, limit = 500) =>
    request<{ ts: string; open: number; high: number; low: number; close: number; volume: number }[]>(
      `/data/ohlcv?symbol=${symbol}&timeframe=${timeframe}&limit=${limit}`
    ),
  symbols: () => request<string[]>("/data/symbols"),
  fetchHistory: (symbol: string, timeframe: string, since: string) =>
    request<{ job_id: string }>("/data/fetch-history", {
      method: "POST",
      body: JSON.stringify({ symbol, timeframe, since }),
    }),

  // Strategies
  strategies: () => request<Strategy[]>("/strategies"),
  createStrategy: (data: Partial<Strategy>) =>
    request<Strategy>("/strategies", { method: "POST", body: JSON.stringify(data) }),
  updateStrategy: (id: string, data: Partial<Strategy>) =>
    request<Strategy>(`/strategies/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteStrategy: (id: string) => request<void>(`/strategies/${id}`, { method: "DELETE" }),

  // Model training
  models: () => request<ModelArtifact[]>("/models"),
  trainModel: (strategyId: string, params: Record<string, unknown>) =>
    request<{ job_id: string }>("/models/train", {
      method: "POST",
      body: JSON.stringify({ strategy_id: strategyId, params }),
    }),
  deployModel: (id: number) =>
    request<void>(`/models/${id}/deploy`, { method: "POST" }),
  jobStatus: (jobId: string) =>
    request<{ status: string; result?: unknown }>(`/models/jobs/${jobId}`),

  // Backtests
  backtests: () => request<BacktestResult[]>("/backtests"),
  runBacktest: (config: BacktestConfig) =>
    request<{ backtest_id: string }>("/backtests", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  backtest: (id: string) => request<BacktestResult>(`/backtests/${id}`),

  // Live trading
  liveStatus: () => request<LiveStatus>("/live/status"),
  startTrader: () => request<void>("/live/start", { method: "POST" }),
  stopTrader: () => request<void>("/live/stop", { method: "POST" }),
  killSwitch: (reason: string) =>
    request<void>("/live/kill", { method: "POST", body: JSON.stringify({ reason }) }),
  positions: () => request<Position[]>("/live/positions"),
  orders: () => request<Order[]>("/live/orders"),

  // Risk
  riskSettings: () => request<RiskSettings>("/risk/settings"),
  updateRiskSettings: (data: Partial<RiskSettings>) =>
    request<RiskSettings>("/risk/settings", { method: "PATCH", body: JSON.stringify(data) }),
  riskMetrics: () => request<RiskMetrics>("/risk/metrics"),
};

// Types
export interface Strategy {
  id: string; name: string; description: string;
  config: Record<string, unknown>; status: string;
  created_at: string; updated_at: string;
}
export interface ModelArtifact {
  id: number; strategy_id: string; artifact_path: string;
  strategy_type: string; cv_scores: unknown; is_champion: boolean; created_at: string;
}
export interface BacktestConfig {
  strategy_id: string; symbol: string; timeframe: string;
  start_date: string; end_date: string;
  initial_capital?: number; model_path?: string;
}
export interface BacktestResult {
  id: string; strategy_id: string; config: BacktestConfig;
  results?: { metrics: Record<string, number>; equity_curve: unknown[]; trade_log: unknown[] };
  status: string; created_at: string;
}
export interface LiveStatus {
  running: boolean; trading_enabled: boolean;
  equity: number; ts: string; age_seconds: number;
}
export interface Position {
  symbol: string; qty: number; avg_price: number; unrealized_pnl: number;
}
export interface Order {
  client_order_id: string; exchange_order_id: string; symbol: string;
  side: string; order_type: string; qty: number; filled_qty: number;
  avg_fill_price: number; status: string; created_at: string;
}
export interface RiskSettings {
  max_daily_loss_pct: number; max_drawdown_pct: number;
  max_position_notional_pct: number; max_open_orders: number;
  max_order_rate_per_min: number; leverage_limit: number;
  symbol_whitelist: string[];
}
export interface RiskMetrics {
  var_95: number; es_95: number; current_drawdown: number; daily_pnl: number;
}
