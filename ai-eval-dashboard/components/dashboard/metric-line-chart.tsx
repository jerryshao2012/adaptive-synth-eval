"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";

interface ChartDataPoint {
  timestamp: string;
  value: number;
  status?: string;
  version?: string;
}

interface MetricLineChartProps {
  data: ChartDataPoint[];
  warnThreshold?: number;
  failThreshold?: number;
  yDomain?: [number, number | "auto"];
  valueFormatter?: (v: number) => string;
  className?: string;
}

export function MetricLineChart({
  data,
  warnThreshold,
  failThreshold,
  yDomain = [0, 100] as [number, number | "auto"],
  valueFormatter = (v) => `${v}`,
  className,
}: MetricLineChartProps) {
  const formattedData = useMemo(
    () =>
      data.map((d) => ({
        ...d,
        time: format(parseISO(d.timestamp), "MMM d"),
        isoTime: d.timestamp,
      })),
    [data]
  );

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-sm text-muted-foreground">
        No data for this period
      </div>
    );
  }

  return (
    <div className={cn("h-[200px] w-full", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formattedData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(214 26% 24%)"
            strokeOpacity={0.4}
            vertical={false}
          />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 11, fill: "hsl(214 26% 77%)" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={yDomain}
            tick={{ fontSize: 11, fill: "hsl(214 26% 77%)" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={valueFormatter}
            width={40}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const point = payload[0].payload;
              return (
                <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-lg">
                  <p className="font-medium text-foreground mb-0.5">
                    {format(parseISO(point.isoTime), "PPp")}
                  </p>
                  <p className="text-muted-foreground">
                    Score:{" "}
                    <span className="font-semibold text-foreground">
                      {valueFormatter(point.value)}
                    </span>
                  </p>
                  {point.status && (
                    <p className="text-muted-foreground">
                      Status:{" "}
                      <span className="font-medium capitalize">{point.status}</span>
                    </p>
                  )}
                </div>
              );
            }}
          />
          {failThreshold !== undefined && (
            <ReferenceLine
              y={failThreshold}
              stroke="hsl(0 100% 47%)"
              strokeDasharray="4 4"
              strokeOpacity={0.6}
              label={{
                value: `Fail: ${failThreshold}`,
                position: "insideBottomRight",
                fontSize: 10,
                fill: "hsl(0 100% 47%)",
              }}
            />
          )}
          {warnThreshold !== undefined && (
            <ReferenceLine
              y={warnThreshold}
              stroke="hsl(43 74% 66%)"
              strokeDasharray="4 4"
              strokeOpacity={0.6}
              label={{
                value: `Warn: ${warnThreshold}`,
                position: "insideTopRight",
                fontSize: 10,
                fill: "hsl(43 74% 66%)",
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey="value"
            stroke="hsl(220 85% 43%)"
            strokeWidth={2}
            dot={{ r: 3, fill: "hsl(220 85% 43%)" }}
            activeDot={{ r: 5, fill: "hsl(220 85% 43%)" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
