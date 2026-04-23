import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Strategy } from "../lib/api";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Table, Thead, Tbody, Th, Td, Tr } from "../components/ui/table";
import { Plus, Trash2 } from "lucide-react";

const PARADIGMS = ["supervised", "deep_learning", "rl"] as const;
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

const statusColor: Record<string, "green" | "gray" | "yellow"> = {
  active: "green", inactive: "gray", paper: "yellow",
};

export default function Strategies() {
  const qc = useQueryClient();
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [paradigm, setParadigm] = useState<string>("supervised");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1h");

  const createMutation = useMutation({
    mutationFn: () => api.createStrategy({ name, paradigm, symbol, timeframe }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies"] });
      setShowForm(false);
      setName("");
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteStrategy(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["strategies"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Strategies</h1>
        <Button onClick={() => setShowForm(!showForm)} size="sm"><Plus size={14} /> New</Button>
      </div>

      {showForm && (
        <Card>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="col-span-2 md:col-span-1">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Strategy" />
            </div>
            <div>
              <Label>Paradigm</Label>
              <Select value={paradigm} onChange={(e) => setParadigm(e.target.value)}>
                {PARADIGMS.map((p) => <option key={p} value={p}>{p}</option>)}
              </Select>
            </div>
            <div>
              <Label>Symbol</Label>
              <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="BTC/USDT" />
            </div>
            <div>
              <Label>Timeframe</Label>
              <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
              </Select>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            <Button onClick={() => createMutation.mutate()} disabled={!name || createMutation.isPending}>
              {createMutation.isPending ? "Creating…" : "Create"}
            </Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
          </div>
        </Card>
      )}

      <Card>
        {strategies.length === 0 ? (
          <p className="text-sm text-gray-500">No strategies yet — click New to create one.</p>
        ) : (
          <Table>
            <Thead><tr><Th>Name</Th><Th>Paradigm</Th><Th>Symbol</Th><Th>Timeframe</Th><Th>Status</Th><Th>Created</Th><Th></Th></tr></Thead>
            <Tbody>
              {strategies.map((s: Strategy) => (
                <Tr key={s.id}>
                  <Td className="font-medium text-gray-100">{s.name}</Td>
                  <Td>{s.paradigm}</Td>
                  <Td>{s.symbol}</Td>
                  <Td>{s.timeframe}</Td>
                  <Td><Badge color={statusColor[s.status] ?? "gray"}>{s.status}</Badge></Td>
                  <Td>{new Date(s.created_at).toLocaleDateString()}</Td>
                  <Td>
                    <Button variant="ghost" size="sm" onClick={() => deleteMutation.mutate(s.id)}>
                      <Trash2 size={14} className="text-red-400" />
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
