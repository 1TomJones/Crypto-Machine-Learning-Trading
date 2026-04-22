import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, RiskSettings as RS } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { Alert } from "../components/ui/alert";
import { pct, fmt } from "../lib/utils";

export default function RiskSettings() {
  const qc = useQueryClient();
  const { data: settings, isLoading } = useQuery({ queryKey: ["riskSettings"], queryFn: api.riskSettings });
  const { data: metrics } = useQuery({ queryKey: ["riskMetrics"], queryFn: api.riskMetrics, refetchInterval: 30000 });

  const [form, setForm] = useState<Partial<RS>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: () => api.updateRiskSettings(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["riskSettings"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  function field(key: keyof RS, label: string, type: "number" | "text" = "number") {
    return (
      <div key={key}>
        <Label>{label}</Label>
        <Input
          type={type}
          step={type === "number" ? "0.001" : undefined}
          value={String(form[key] ?? "")}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              [key]: type === "number" ? parseFloat(e.target.value) : e.target.value,
            }))
          }
        />
      </div>
    );
  }

  if (isLoading) return <p className="text-gray-400">Loading…</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Risk Settings</h1>

      {/* Live metrics */}
      {metrics && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            ["VaR 95%", pct(metrics.var_95)],
            ["ES 95%", pct(metrics.es_95)],
            ["Drawdown", pct(metrics.current_drawdown)],
            ["Daily PnL", fmt(metrics.daily_pnl)],
          ].map(([k, v]) => (
            <Card key={k}>
              <p className="text-xs text-gray-400 uppercase tracking-wide">{k}</p>
              <p className="mt-1 text-xl font-bold text-gray-100">{v}</p>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader><CardTitle>Limits</CardTitle></CardHeader>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          {field("max_daily_loss_pct",       "Max Daily Loss %")}
          {field("max_drawdown_pct",          "Max Drawdown %")}
          {field("max_position_notional_pct", "Max Position Notional %")}
          {field("max_open_orders",           "Max Open Orders")}
          {field("max_order_rate_per_min",    "Max Orders / Min")}
          {field("leverage_limit",            "Leverage Limit")}
        </div>
        <div className="mt-3">
          <Label>Symbol Whitelist (comma-separated)</Label>
          <Input
            value={(form.symbol_whitelist ?? []).join(", ")}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                symbol_whitelist: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              }))
            }
          />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Saving…" : "Save"}
          </Button>
          {saved && <Alert variant="success" className="py-1 px-3">Saved.</Alert>}
          {updateMutation.isError && (
            <Alert variant="error" className="py-1 px-3">
              {(updateMutation.error as Error).message}
            </Alert>
          )}
        </div>
      </Card>
    </div>
  );
}
