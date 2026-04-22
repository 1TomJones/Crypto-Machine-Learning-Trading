import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Order } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Table, Thead, Tbody, Th, Td, Tr } from "../components/ui/table";
import { Alert } from "../components/ui/alert";
import { fmt } from "../lib/utils";
import { Play, Square, Zap } from "lucide-react";

export default function LiveDeployment() {
  const qc = useQueryClient();
  const [killReason, setKillReason] = useState("");
  const [showKillConfirm, setShowKillConfirm] = useState(false);

  const { data: status, isLoading } = useQuery({
    queryKey: ["liveStatus"],
    queryFn: api.liveStatus,
    refetchInterval: 5000,
  });
  const { data: orders = [] } = useQuery({
    queryKey: ["orders"],
    queryFn: api.orders,
    refetchInterval: 10000,
  });

  const startMutation = useMutation({
    mutationFn: api.startTrader,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["liveStatus"] }),
  });
  const stopMutation = useMutation({
    mutationFn: api.stopTrader,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["liveStatus"] }),
  });
  const killMutation = useMutation({
    mutationFn: () => api.killSwitch(killReason || "Manual kill via UI"),
    onSuccess: () => {
      setShowKillConfirm(false);
      qc.invalidateQueries({ queryKey: ["liveStatus"] });
    },
  });

  const isRunning = status?.running;
  const isTradingEnabled = status?.trading_enabled;

  const orderStatusColor: Record<string, "green" | "yellow" | "red" | "gray"> = {
    filled: "green", open: "yellow", partial: "yellow",
    cancelled: "gray", rejected: "red", expired: "gray",
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Live Trading</h1>

      {/* Status + controls */}
      <Card>
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${isRunning ? "bg-green-400 animate-pulse" : "bg-gray-600"}`} />
              <span className="text-sm font-medium text-gray-200">
                {isLoading ? "Loading…" : isRunning ? "Trader Running" : "Trader Stopped"}
              </span>
              {isRunning && (
                <Badge color={isTradingEnabled ? "green" : "yellow"}>
                  {isTradingEnabled ? "Trading" : "Paused"}
                </Badge>
              )}
            </div>
            {status?.equity != null && (
              <p className="text-xs text-gray-400">Equity: <span className="text-gray-200 font-medium">{fmt(status.equity)}</span></p>
            )}
            {status?.age_seconds != null && (
              <p className="text-xs text-gray-500">Heartbeat {Math.round(status.age_seconds)}s ago</p>
            )}
          </div>

          <div className="flex items-center gap-2">
            {!isRunning ? (
              <Button onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>
                <Play size={14} /> Start
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending}>
                <Square size={14} /> Stop
              </Button>
            )}
            <Button variant="danger" onClick={() => setShowKillConfirm(true)}>
              <Zap size={14} /> Kill Switch
            </Button>
          </div>
        </div>

        {showKillConfirm && (
          <div className="mt-4 space-y-3 border-t border-gray-800 pt-4">
            <Alert variant="error">
              <strong>EMERGENCY KILL SWITCH</strong>: This will cancel all orders, flatten all positions, and halt trading immediately. Manual restart required.
            </Alert>
            <input
              className="w-full rounded-lg border border-red-800 bg-gray-800 px-3 py-1.5 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none"
              placeholder="Reason (optional)"
              value={killReason}
              onChange={(e) => setKillReason(e.target.value)}
            />
            <div className="flex gap-2">
              <Button variant="danger" onClick={() => killMutation.mutate()} disabled={killMutation.isPending}>
                {killMutation.isPending ? "Triggering…" : "CONFIRM KILL"}
              </Button>
              <Button variant="ghost" onClick={() => setShowKillConfirm(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </Card>

      {/* Recent orders */}
      <Card>
        <CardHeader><CardTitle>Recent Orders</CardTitle></CardHeader>
        <Table>
          <Thead>
            <tr>
              <Th>Client ID</Th><Th>Symbol</Th><Th>Side</Th><Th>Type</Th>
              <Th>Qty</Th><Th>Filled</Th><Th>Avg Price</Th><Th>Status</Th><Th>Time</Th>
            </tr>
          </Thead>
          <Tbody>
            {(orders as Order[]).slice(0, 20).map((o) => (
              <Tr key={o.client_order_id}>
                <Td className="font-mono text-xs">{o.client_order_id.slice(0, 8)}</Td>
                <Td>{o.symbol}</Td>
                <Td><Badge color={o.side === "buy" ? "green" : "red"}>{o.side}</Badge></Td>
                <Td className="text-xs">{o.order_type}</Td>
                <Td>{fmt(o.qty, 6)}</Td>
                <Td>{fmt(o.filled_qty, 6)}</Td>
                <Td>{o.avg_fill_price ? fmt(o.avg_fill_price) : "—"}</Td>
                <Td><Badge color={orderStatusColor[o.status] ?? "gray"}>{o.status}</Badge></Td>
                <Td className="text-xs">{new Date(o.created_at).toLocaleTimeString()}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
        {orders.length === 0 && <p className="py-4 text-center text-sm text-gray-500">No orders.</p>}
      </Card>
    </div>
  );
}
