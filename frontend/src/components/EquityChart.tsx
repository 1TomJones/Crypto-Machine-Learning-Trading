import { useEffect, useRef } from "react";
import { createChart, IChartApi, AreaSeries } from "lightweight-charts";

interface Point { ts: string; equity: number; }

export default function EquityChart({ data }: { data: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !data.length) return;
    const chart = createChart(ref.current, {
      layout: { background: { color: "#111827" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
      width: ref.current.clientWidth,
      height: 260,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#0ea5e9", topColor: "#0ea5e930", bottomColor: "transparent",
    });
    series.setData(
      data.map((p) => ({
        time: (new Date(p.ts).getTime() / 1000) as unknown as string,
        value: p.equity,
      }))
    );
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => chart.applyOptions({ width: ref.current!.clientWidth }));
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [data]);

  return <div ref={ref} className="w-full" />;
}
