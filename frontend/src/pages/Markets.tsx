import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Button } from "../components/ui/button";
import CandlestickChart from "../components/CandlestickChart";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"];

export default function Markets() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1h");

  const { data: symbolRows = [] } = useQuery({ queryKey: ["symbols"], queryFn: api.symbols });
  const { data: bars = [], isFetching } = useQuery({
    queryKey: ["ohlcv", symbol, timeframe],
    queryFn: () => api.ohlcv(symbol, timeframe, 500),
    refetchInterval: 60_000,
  });

  const seedMutation = useMutation({
    mutationFn: () => api.seedData(symbol, timeframe, 500),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["symbols"] });
      qc.invalidateQueries({ queryKey: ["ohlcv", symbol, timeframe] });
    },
  });

  const knownSymbols = symbolRows.map((r) => r.symbol);
  const allSymbols = Array.from(new Set([...knownSymbols, ...DEFAULT_SYMBOLS]));

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Markets</h1>
      <div className="flex gap-3 flex-wrap items-center">
        <Select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-40">
          {allSymbols.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className="w-28">
          {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
        </Select>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => seedMutation.mutate()}
          disabled={seedMutation.isPending}
        >
          {seedMutation.isPending ? "Fetching…" : "Fetch Latest"}
        </Button>
        {seedMutation.isSuccess && (
          <span className="text-xs text-green-400">
            Loaded {(seedMutation.data as { inserted: number }).inserted} candles
          </span>
        )}
        {seedMutation.isError && (
          <span className="text-xs text-red-400">
            {(seedMutation.error as Error).message}
          </span>
        )}
      </div>
      <Card>
        {isFetching && <p className="text-xs text-gray-500 mb-2">Loading…</p>}
        {bars.length === 0 && !isFetching ? (
          <p className="text-sm text-gray-500">No data yet — click Fetch Latest to load candles from Binance.</p>
        ) : (
          <CandlestickChart bars={bars} />
        )}
      </Card>
    </div>
  );
}
