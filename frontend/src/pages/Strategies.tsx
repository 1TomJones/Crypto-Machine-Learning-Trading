import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Strategy } from "../lib/api";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input, Label } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Table, Thead, Tbody, Th, Td, Tr } from "../components/ui/table";
import { Plus, Trash2 } from "lucide-react";

const statusColor: Record<string, "green" | "gray" | "yellow"> = {
  active: "green", draft: "gray", inactive: "yellow",
};

export default function Strategies() {
  const qc = useQueryClient();
  const { data: strategies = [] } = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const createMutation = useMutation({
    mutationFn: () => api.createStrategy({ name, description, status: "draft" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["strategies"] }); setShowForm(false); setName(""); setDescription(""); },
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
          <div className="space-y-3">
            <div><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div><Label>Description</Label><Input value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div className="flex gap-2">
              <Button onClick={() => createMutation.mutate()} disabled={!name || createMutation.isPending}>Create</Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <Table>
          <Thead><tr><Th>Name</Th><Th>Description</Th><Th>Status</Th><Th>Created</Th><Th></Th></tr></Thead>
          <Tbody>
            {strategies.map((s: Strategy) => (
              <Tr key={s.id}>
                <Td className="font-medium text-gray-100">{s.name}</Td>
                <Td className="max-w-xs truncate">{s.description}</Td>
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
      </Card>
    </div>
  );
}
