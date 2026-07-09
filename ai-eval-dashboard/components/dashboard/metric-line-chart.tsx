"use client";

import { useMemo } from "react";
import {
  LineChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
} from "recharts";
import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import type { MetricPointIdentity, TimePeriodPreset } from "@/types/evaluation";

interface ChartDataPoint {
  timestamp: string;
  value: number;
  status?: string;
  version?: string;
  pointIdentity?: MetricPointIdentity;
}

interface MetricLineChartProps {
  data: ChartDataPoint[];
  period?: TimePeriodPreset;
  warnThreshold?: number;
  failThreshold?: number;
  yDomain?: [number, number | "auto"];
  valueFormatter?: (v: number) => string;
  className?: string;
  onPointClick?: (point: MetricPointIdentity) => void;
}

export function MetricLineChart({
  data,
  period,
  warnThreshold,
  failThreshold,
  yDomain = [0, 100] as [number, number | "auto"],
  valueFormatter = (v) => `${v}`,
  className,
  onPointClick,
}: MetricLineChartProps) {
  const lineColor = "hsl(206 85% 42%)";

  const emitPointIfPresent = (candidate: unknown) => {
    if (!onPointClick || !candidate || typeof candidate !== "object") return;
    const maybe = candidate as { pointIdentity?: MetricPointIdentity };
    if (maybe.pointIdentity) {
      onPointClick(maybe.pointIdentity);
    }
  };

  const formatTick = (isoTime: string) => {
    const date = parseISO(isoTime);
    switch (period) {
      case "this-week":
      case "last-7-days":
        return format(date, "EEE d");
      case "this-month":
      case "last-30-days":
        return format(date, "MMM d");
      case "this-quarter":
      case "last-90-days":
        return format(date, "MMM d");
      default:
        return format(date, "MMM d");
    }
  };

  const formattedData = useMemo(
    () =>
      data.map((d) => ({
        ...d,
        isoTime: d.timestamp,
      })),
    [data]
  );

  const forecastStartIndex = useMemo(
    () => Math.max(0, Math.floor(formattedData.length * 0.88)),
    [formattedData]
  );
  const forecastStart = formattedData[forecastStartIndex]?.isoTime;
  const forecastEnd = formattedData[formattedData.length - 1]?.isoTime;

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-sm text-muted-foreground">
        No data for this period
      </div>
    );
  }

  return (
    <div className={cn("h-[200px] w-full", className)}>
      <ResponsiveContainer width="100%" height="100%" key={`${period ?? "default"}-${data.length}`}>
        <LineChart
          data={formattedData}
          margin={{ top: 8, right: 8, bottom: 14, left: 0 }}
          onClick={(state) => {
            if (!onPointClick || !state || typeof state !== "object") return;
            const maybeState = state as {
              activePayload?: Array<{ payload?: ChartDataPoint }>;
            };
            emitPointIfPresent(maybeState.activePayload?.[0]?.payload);
          }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(210 20% 78%)"
            strokeOpacity={0.6}
            vertical
          />
          <XAxis
            dataKey="isoTime"
            tick={{ fontSize: 11, fill: "hsl(210 12% 35%)" }}
            tickLine={false}
            axisLine={{ stroke: "hsl(210 18% 72%)" }}
            interval="preserveStartEnd"
            tickFormatter={(value) => formatTick(String(value))}
            height={32}
            minTickGap={20}
          />
          <YAxis
            domain={yDomain}
            tick={{ fontSize: 11, fill: "hsl(210 12% 35%)" }}
            tickLine={false}
            axisLine={{ stroke: "hsl(210 18% 72%)" }}
            tickFormatter={valueFormatter}
            width={40}
          />
          <defs>
            <linearGradient id="metricAreaFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.38} />
              <stop offset="30%" stopColor={lineColor} stopOpacity={0.28} />
              <stop offset="62%" stopColor={lineColor} stopOpacity={0.16} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0.05} />
            </linearGradient>
            <linearGradient id="metricAreaGrade" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.12} />
              <stop offset="24%" stopColor={lineColor} stopOpacity={0.12} />
              <stop offset="24%" stopColor={lineColor} stopOpacity={0.08} />
              <stop offset="48%" stopColor={lineColor} stopOpacity={0.08} />
              <stop offset="48%" stopColor={lineColor} stopOpacity={0.05} />
              <stop offset="72%" stopColor={lineColor} stopOpacity={0.05} />
              <stop offset="72%" stopColor={lineColor} stopOpacity={0.025} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0.025} />
            </linearGradient>
            <linearGradient id="metricForecastBand" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(148 45% 46%)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="hsl(148 45% 46%)" stopOpacity={0.06} />
            </linearGradient>
          </defs>
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
          {forecastStart && forecastEnd && forecastStart !== forecastEnd && (
            <ReferenceArea
              x1={forecastStart}
              x2={forecastEnd}
              y1={yDomain[0]}
              y2={typeof yDomain[1] === "number" ? yDomain[1] : undefined}
              fill="url(#metricForecastBand)"
              fillOpacity={1}
              ifOverflow="visible"
              strokeOpacity={0}
            />
          )}
          <Area
            type="monotone"
            dataKey="value"
            stroke="none"
            fill="url(#metricAreaFill)"
            isAnimationActive={false}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="none"
            fill="url(#metricAreaGrade)"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={lineColor}
            strokeWidth={3}
            dot={(dotProps: unknown) => {
              const p = dotProps as {
                cx?: number;
                cy?: number;
                payload?: ChartDataPoint;
              };
              if (typeof p.cx !== "number" || typeof p.cy !== "number") {
                return null;
              }

              const payload = p.payload;
              return (
                <g
                  className={onPointClick ? "cursor-pointer" : undefined}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (payload?.pointIdentity && onPointClick) {
                      onPointClick(payload.pointIdentity);
                    }
                  }}
                >
                  <circle cx={p.cx} cy={p.cy} r={12} fill="transparent" />
                  <circle cx={p.cx} cy={p.cy} r={5} fill={lineColor} stroke="white" strokeWidth={1.3} />
                </g>
              );
            }}
            activeDot={{ r: 7, fill: lineColor, stroke: "white", strokeWidth: 1.6 }}
            onClick={(...args: unknown[]) => {
              if (!onPointClick) return;
              for (const arg of args) {
                if (arg && typeof arg === "object" && "payload" in arg) {
                  emitPointIfPresent((arg as { payload?: ChartDataPoint }).payload);
                }
                emitPointIfPresent(arg);
              }
            }}
            className={onPointClick ? "cursor-pointer" : undefined}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
