import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { fmt, pct } from "../lib/utils";
import EquityChart from "../components/EquityChart";
import { useWebSocket } from "../hooks/useWebSocket";
import { useTickerStore } from "../lib/store";

export default function Dashboard() {
  const { data: status } = useQuery({ queryKey: ["liveStatus"], queryFn: api.liveStatus, refetchInterval: 5000 });
  const { data: metrics } = useQuery({ queryKey: ["riskMetrics"], queryFn: api.riskMetrics, refetchInterval: 30000 });
  const { data: positions } = useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: 10000 });
  const setPrice = useTickerStore((s) => s.setPrice);
  const prices = useTickerStore((s) => s.prices);

  useWebSocket("trader:ticks", (msg: unknown) => {
    const m = msg as { symbol: string; close: number };
    if (m?.symbol && m?.close) setPrice(m.symbol, m.close);
  });

  const isRunning = status?.running;
  const equity = status?.equity ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Dashboard</h1>
        <Badge color={isRunning ? "green" : "red"}>{isRunning ? "Trading Live" : "Stopped"}</Badge>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Equity" value={`£${fmt(equity)}`} />
        <StatCard label="Daily VaR 95%" value={metrics ? pct(metrics.var_95) : "—"} />
        <StatCard label="ES 95%" value={metrics ? pct(metrics.es_95) : "—"} />
        <StatCard label="Drawdown" value={metrics ? pct(metrics.current_drawdown) : "—"} />
      </div>

      {/* Positions */}
      <Card>
        <CardHeader><CardTitle>Open Positions</CardTitle></CardHeader>
        {positions?.length ? (
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-400 uppercase border-b border-gray-800">
              <tr>
                {["Symbol", "Qty", "Avg Price", "Live Price", "Unrealised PnL"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.symbol} className="border-b border-gray-800/50">
                  <td className="px-3 py-2 font-mono">{pos.symbol}</td>
                  <td className="px-3 py-2">{fmt(pos.qty, 6)}</td>
                  <td className="px-3 py-2">{fmt(Number(pos.avg_entry_price))}</td>
                  <td className="px-3 py-2">{prices[pos.symbol] ? fmt(prices[pos.symbol]) : "—"}</td>
                  <td className={`px-3 py-2 font-medium ${Number(pos.unrealized_pnl) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {Number(pos.unrealized_pnl) >= 0 ? "+" : ""}{fmt(Number(pos.unrealized_pnl))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-gray-500">No open positions.</p>
        )}
      </Card>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-100">{value}</p>
    </Card>
  );
}
