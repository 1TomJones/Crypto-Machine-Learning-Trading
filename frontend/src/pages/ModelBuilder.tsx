import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ModelArtifact } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Table, Thead, Tbody, Th, Td, Tr } from "../components/ui/table";
import { Alert } from "../components/ui/alert";
import { Rocket } from "lucide-react";

const MODEL_TYPES = ["lightgbm", "xgboost", "random_forest", "logistic", "lstm", "ppo"];

export default function ModelBuilder() {
  const qc = useQueryClient();
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const { data: models = [] } = useQuery({ queryKey: ["models"], queryFn: api.models, refetchInterval: 15000 });

  const [strategyId, setStrategyId] = useState("");
  const [modelType, setModelType] = useState("lightgbm");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [startDate, setStartDate] = useState("2021-01-01");
  const [endDate, setEndDate] = useState("2024-01-01");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobMsg, setJobMsg] = useState("");

  const trainMutation = useMutation({
    mutationFn: () =>
      api.trainModel(strategyId, { model_type: modelType, symbol, start_date: startDate, end_date: endDate }),
    onSuccess: (res) => {
      setJobId(res.job_id);
      setJobMsg(`Job submitted: ${res.job_id}`);
      qc.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (e) => setJobMsg(`Error: ${(e as Error).message}`),
  });

  const deployMutation = useMutation({
    mutationFn: (id: string) => api.deployModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Train Model</h1>

      <Card>
        <CardHeader><CardTitle>Training Parameters</CardTitle></CardHeader>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div>
            <Label>Strategy</Label>
            <Select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
              <option value="">Select strategy…</option>
              {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </div>
          <div>
            <Label>Model Type</Label>
            <Select value={modelType} onChange={(e) => setModelType(e.target.value)}>
              {MODEL_TYPES.map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
          </div>
          <div>
            <Label>Symbol</Label>
            <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          </div>
          <div>
            <Label>Start Date</Label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <Label>End Date</Label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>
        <div className="mt-4">
          <Button
            onClick={() => trainMutation.mutate()}
            disabled={!strategyId || trainMutation.isPending}
          >
            {trainMutation.isPending ? "Submitting…" : "Start Training"}
          </Button>
          {jobMsg && <Alert variant={trainMutation.isError ? "error" : "info"} className="mt-3">{jobMsg}</Alert>}
        </div>
      </Card>

      <Card>
        <CardHeader><CardTitle>Model Artifacts</CardTitle></CardHeader>
        <Table>
          <Thead>
            <tr><Th>ID</Th><Th>Strategy</Th><Th>Type</Th><Th>Champion</Th><Th>Created</Th><Th></Th></tr>
          </Thead>
          <Tbody>
            {(models as ModelArtifact[]).map((m) => (
              <Tr key={m.id}>
                <Td className="font-mono text-xs">{m.id}</Td>
                <Td>{m.strategy_id}</Td>
                <Td><Badge color="blue">{m.model_type}</Badge></Td>
                <Td>{m.is_champion ? <Badge color="green">Champion</Badge> : "—"}</Td>
                <Td>{new Date(m.created_at).toLocaleDateString()}</Td>
                <Td>
                  {!m.is_champion && (
                    <Button size="sm" variant="secondary" onClick={() => deployMutation.mutate(m.id)}>
                      <Rocket size={12} /> Deploy
                    </Button>
                  )}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </Card>
    </div>
  );
}
