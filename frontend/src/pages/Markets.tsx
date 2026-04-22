import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card } from "../components/ui/card";
import { Select } from "../components/ui/select";
import CandlestickChart from "../components/CandlestickChart";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

export default function Markets() {
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("1h");

  const { data: symbols = [] } = useQuery({ queryKey: ["symbols"], queryFn: api.symbols });
  const { data: bars = [], isFetching } = useQuery({
    queryKey: ["ohlcv", symbol, timeframe],
    queryFn: () => api.ohlcv(symbol, timeframe, 500),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-gray-100">Markets</h1>
      <div className="flex gap-3">
        <Select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-40">
          {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className="w-28">
          {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
        </Select>
      </div>
      <Card>
        {isFetching && <p className="text-xs text-gray-500">Loading…</p>}
        <CandlestickChart bars={bars} />
      </Card>
    </div>
  );
}
