"use client";

import { useMemo } from "react";
import { AreaChart } from "@/components/charts/area-chart";
import { Area } from "@/components/charts/area";
import { Grid } from "@/components/charts/grid";
import { XAxis } from "@/components/charts/x-axis";
import { ChartTooltip } from "@/components/charts/tooltip/chart-tooltip";
import { useReducedMotionSafe } from "@/hooks/useReducedMotionSafe";

export type EquityBklitProps = { labels: string[]; data: number[] };

export function toBklitData(labels: string[], data: number[]) {
  return labels.map((l, i) => {
    // labels are "YYYY-MM-DD HH:mm" — insert T for reliable Date parse
    const iso = l.includes("T") ? l : l.replace(" ", "T");
    const d = new Date(iso);
    return { date: Number.isNaN(d.getTime()) ? new Date() : d, equity: data[i] };
  });
}

export default function EquityChartBklit({ labels, data }: EquityBklitProps) {
  const reduced = useReducedMotionSafe();
  const chartData = useMemo(() => toBklitData(labels, data), [labels, data]);

  if (chartData.length === 0) return null;

  return (
    <div
      role="img"
      aria-label="Equity curve"
      className="w-full overflow-hidden rounded-lg border border-edge bg-[#070707]"
    >
      <AreaChart
        data={chartData as unknown as Record<string, unknown>[]}
        xDataKey="date"
        aspectRatio="2 / 1"
        animationDuration={reduced ? 0 : 1100}
        yDomainTween={!reduced}
        yDomainTweenDuration={reduced ? 0 : 500}
        className="w-full"
      >
        {/* grid + zero-baseline dashed lime — replaces old <line strokeDasharray="3 4"> */}
        <Grid
          horizontal
          vertical={false}
          stroke="#161616"
          strokeDasharray="4 4"
          highlightRowValues={[0]}
          highlightRowStroke="rgba(212,255,63,.22)"
          highlightRowStrokeDasharray="3 4"
          highlightRowStrokeWidth={1}
        />
        <Area
          dataKey="equity"
          fill="var(--lime)"
          fillOpacity={0.18}
          stroke="var(--lime)"
          strokeWidth={2}
        />
        <XAxis numTicks={5} />
        <ChartTooltip />
      </AreaChart>
    </div>
  );
}
