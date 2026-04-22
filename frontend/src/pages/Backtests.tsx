import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, BacktestResult } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Table, Thead, Tbody, Th, Td, Tr } from "../components/ui/table";
import EquityChart from "../components/EquityChart";
import { fmt, pct } from "../lib/utils";

export default function Backtests() {
  const qc = useQueryClient();
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const { data: backtests = [] } = useQuery({ queryKey: ["backtests"], queryFn: api.backtests, refetchInterval: 10000 });

  const [strategyId, setStrategyId] = useState("");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1h");
  const [startDate, setStartDate] = useState("2021-01-01");
  const [endDate, setEndDate] = useState("2024-01-01");
  const [capital, setCapital] = useState("10000");
  const [selected, setSelected] = useState<BacktestResult | null>(null);

  const runMutation = useMutation({
    mutationFn: () =>
      api.runBacktest({ strategy_id: strategyId, symbol, timeframe, start_date: startDate, end_date: endDate, initial_capital: Number(capital) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backtests"] }),
  });

  const statusColor: Record<string, "yellow" | "green" | "red"> = {
    pending: "yellow", completed: "green", failed: "red",
  };

  const metrics = selected?.results?.metrics;
  const curve = (selected?.results?.equity_curve ?? []) as { ts: string; equity: number }[];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Backtests</h1>

      <Card>
        <CardHeader><CardTitle>Run Backtest</CardTitle></CardHeader>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <div>
            <Label>Strategy</Label>
            <Select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
              <option value="">Select…</option>
              {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </div>
          <div><Label>Symbol</Label><Input value={symbol} onChange={(e) => setSymbol(e.target.value)} /></div>
          <div>
            <Label>Timeframe</Label>
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {["1m","5m","15m","1h","4h","1d"].map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </Select>
          </div>
          <div><Label>Start Date</Label><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></div>
          <div><Label>End Date</Label><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></div>
          <div><Label>Capital (£)</Label><Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} /></div>
        </div>
        <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={!strategyId || runMutation.isPending}>
          {runMutation.isPending ? "Submitting…" : "Run"}
        </Button>
      </Card>

      {selected && (
        <Card>
          <CardHeader><CardTitle>Results — {selected.id}</CardTitle></CardHeader>
          {metrics && (
            <div className="grid grid-cols-3 gap-3 mb-4 md:grid-cols-5">
              {[
                ["Sharpe", fmt(metrics.sharpe ?? 0)],
                ["CAGR", pct(metrics.cagr ?? 0)],
                ["Max DD", pct(metrics.max_drawdown ?? 0)],
                ["Win Rate", pct(metrics.win_rate ?? 0)],
                ["Trades", String(metrics.n_trades ?? 0)],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg bg-gray-800 p-3">
                  <p className="text-xs text-gray-400">{k}</p>
                  <p className="text-lg font-bold text-gray-100">{v}</p>
                </div>
              ))}
            </div>
          )}
          <EquityChart data={curve} />
          <Button variant="ghost" size="sm" className="mt-2" onClick={() => setSelected(null)}>Close</Button>
        </Card>
      )}

      <Card>
        <Table>
          <Thead><tr><Th>ID</Th><Th>Strategy</Th><Th>Symbol</Th><Th>Period</Th><Th>Status</Th><Th>Sharpe</Th><Th></Th></tr></Thead>
          <Tbody>
            {(backtests as BacktestResult[]).map((b) => (
              <Tr key={b.id}>
                <Td className="font-mono text-xs">{b.id.slice(0, 8)}</Td>
                <Td>{b.strategy_id}</Td>
                <Td>{b.config?.symbol}</Td>
                <Td className="text-xs">{b.config?.start_date} → {b.config?.end_date}</Td>
                <Td><Badge color={statusColor[b.status] ?? "gray"}>{b.status}</Badge></Td>
                <Td>{b.results?.metrics?.sharpe != null ? fmt(b.results.metrics.sharpe) : "—"}</Td>
                <Td>
                  <Button size="sm" variant="ghost" onClick={() => setSelected(b)}>View</Button>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </Card>
    </div>
  );
}
