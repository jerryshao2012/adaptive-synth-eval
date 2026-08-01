"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import type {
  MetricPointIdentity,
  ProfilePeriod,
  TimePeriodPreset,
} from "@/types/evaluation";

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
  profilePeriods?: ProfilePeriod[];
}

const PHASE_COLORS = [
  "hsl(206 85% 42%)",
  "hsl(270 65% 52%)",
  "hsl(157 62% 38%)",
  "hsl(32 85% 48%)",
  "hsl(338 68% 50%)",
];

function phaseColor(periodId: string): string {
  let hash = 0;
  for (const character of periodId) {
    hash = (hash * 31 + character.charCodeAt(0)) | 0;
  }
  return PHASE_COLORS[Math.abs(hash) % PHASE_COLORS.length];
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
  profilePeriods = [],
}: MetricLineChartProps) {
  const lineColor = "hsl(206 85% 42%)";
  const [clickedPointKey, setClickedPointKey] = useState<string | null>(null);
  const clickFeedbackTimerRef = useRef<number | null>(null);
  const suppressChartFallbackUntilRef = useRef<number>(0);
  const lastSelectedRef = useRef<{ key: string; at: number } | null>(null);

  const makePointKey = (point: MetricPointIdentity | undefined): string | null => {
    if (!point) return null;
    return [
      point.runId,
      point.conversationId || "",
      point.turnId,
      point.timestamp,
      point.metricGroup,
      point.metricKey,
    ].join("|");
  };

  const triggerClickFeedback = (point: MetricPointIdentity | undefined) => {
    const key = makePointKey(point);
    if (!key) return;

    setClickedPointKey(key);
    if (clickFeedbackTimerRef.current) {
      window.clearTimeout(clickFeedbackTimerRef.current);
    }
    clickFeedbackTimerRef.current = window.setTimeout(() => {
      setClickedPointKey(null);
    }, 550);
  };

  useEffect(() => {
    return () => {
      if (clickFeedbackTimerRef.current) {
        window.clearTimeout(clickFeedbackTimerRef.current);
      }
    };
  }, []);

  const selectPoint = (point: MetricPointIdentity | undefined) => {
    if (!point || !onPointClick) return;
    const key = makePointKey(point);
    if (!key) return;

    const now = new Date().getTime();
    const last = lastSelectedRef.current;
    if (last && last.key === key && now - last.at < 240) {
      return;
    }

    lastSelectedRef.current = { key, at: now };
    suppressChartFallbackUntilRef.current = now + 240;
    triggerClickFeedback(point);
    onPointClick(point);
  };

  const formatTick = (timeMs: number) => {
    const date = new Date(timeMs);
    switch (period) {
      case "full-run":
        return format(date, "MMM d, yy");
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
        timeMs: Date.parse(d.timestamp),
      })).filter((point) => Number.isFinite(point.timeMs)),
    [data]
  );
  const phaseBands = useMemo(() => {
    if (formattedData.length === 0 || profilePeriods.length === 0) return [];

    const firstTimeMs = formattedData[0].timeMs;
    const lastTimeMs = formattedData[formattedData.length - 1].timeMs;
    const extentStart = Math.min(firstTimeMs, lastTimeMs);
    const extentEnd = Math.max(firstTimeMs, lastTimeMs);
    const labeledPeriodIds = new Set<string>();

    return profilePeriods.flatMap((profilePeriod) => {
      const startMs = Date.parse(profilePeriod.start);
      const endMs = Date.parse(profilePeriod.end);
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return [];

      const x1 = Math.max(Math.min(startMs, endMs), extentStart);
      const x2 = Math.min(Math.max(startMs, endMs), extentEnd);
      if (x2 <= x1) return [];

      const showLabel = !labeledPeriodIds.has(profilePeriod.periodId);
      labeledPeriodIds.add(profilePeriod.periodId);
      return [
        {
          ...profilePeriod,
          x1,
          x2,
          color: phaseColor(profilePeriod.periodId),
          showLabel,
        },
      ];
    });
  }, [formattedData, profilePeriods]);
  const chartRenderKey =
    `${period ?? "default"}-${formattedData[0]?.isoTime ?? ""}-${formattedData[formattedData.length - 1]?.isoTime ?? ""}-${formattedData.length}-${phaseBands.length}`;

  if (formattedData.length === 0) {
    return (
      <div className="flex items-center justify-center h-50 text-sm text-muted-foreground">
        No data for this period
      </div>
    );
  }

  return (
    <div className={cn("h-50 w-full", className)}>
      <ResponsiveContainer width="100%" height="100%" key={chartRenderKey}>
        <ComposedChart
          data={formattedData}
          margin={{ top: 8, right: 8, bottom: 14, left: 0 }}
          onClick={(state) => {
            if (!onPointClick || !state || typeof state !== "object") return;
            if (Date.now() < suppressChartFallbackUntilRef.current) return;

            const maybeState = state as {
              activePayload?: Array<{ payload?: ChartDataPoint }>;
              activeLabel?: number;
            };
            const fromPayload = maybeState.activePayload?.[0]?.payload?.pointIdentity;
            const fromActiveLabel = maybeState.activeLabel !== undefined
              ? formattedData.find((d) => d.timeMs === Number(maybeState.activeLabel))?.pointIdentity
              : undefined;
            const fallbackPoint = fromPayload || fromActiveLabel;
            selectPoint(fallbackPoint);
          }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="hsl(210 20% 78%)"
            strokeOpacity={0.6}
            vertical
          />
          <XAxis
            dataKey="timeMs"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tick={{ fontSize: 11, fill: "hsl(210 12% 35%)" }}
            tickLine={false}
            axisLine={{ stroke: "hsl(210 18% 72%)" }}
            interval="preserveStartEnd"
            tickFormatter={(value) => formatTick(Number(value))}
            height={32}
            minTickGap={20}
          />
          <YAxis
            domain={yDomain}
            padding={{ top: 4, bottom: 10 }}
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
          </defs>
          {phaseBands.map((band) => (
            <ReferenceArea
              key={band.instanceId}
              x1={band.x1}
              x2={band.x2}
              fill={band.color}
              fillOpacity={0.08}
              stroke={band.color}
              strokeOpacity={0.14}
              ifOverflow="hidden"
              label={
                band.showLabel
                  ? {
                      value: band.periodId,
                      position: "insideTopLeft",
                      fontSize: 9,
                      fill: band.color,
                    }
                  : undefined
              }
            />
          ))}
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
            isAnimationActive={false}
            dot={
              formattedData.length <= 50
                ? (dotProps: unknown) => {
                    const p = dotProps as {
                      cx?: number;
                      cy?: number;
                      payload?: ChartDataPoint;
                    };
                    if (typeof p.cx !== "number" || typeof p.cy !== "number") {
                      return null;
                    }

                    const payload = p.payload;
                    const handlePointPress = (event: { stopPropagation: () => void }) => {
                      event.stopPropagation();
                      if (payload?.pointIdentity && onPointClick) {
                        selectPoint(payload.pointIdentity);
                      }
                    };

                    const pointKey = makePointKey(payload?.pointIdentity);
                    const isClicked = Boolean(pointKey && pointKey === clickedPointKey);

                    return (
                      <g
                        className={onPointClick ? "cursor-pointer" : undefined}
                        onPointerDown={handlePointPress}
                        onMouseDown={handlePointPress}
                        onClick={handlePointPress}
                      >
                        <circle cx={p.cx} cy={p.cy} r={15} fill="transparent" pointerEvents="all" />
                        {isClicked && (
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={10}
                            fill="none"
                            stroke={lineColor}
                            strokeOpacity={0.35}
                            strokeWidth={2}
                            className="animate-ping"
                          />
                        )}
                        {isClicked && (
                          <circle
                            cx={p.cx}
                            cy={p.cy}
                            r={8}
                            fill="none"
                            stroke={lineColor}
                            strokeOpacity={0.65}
                            strokeWidth={2}
                          />
                        )}
                        <circle cx={p.cx} cy={p.cy} r={5} fill={lineColor} stroke="white" strokeWidth={1.3} />
                      </g>
                    );
                  }
                : false
            }
            activeDot={{ r: 7, fill: lineColor, stroke: "white", strokeWidth: 1.6 }}
            className={onPointClick ? "cursor-pointer" : undefined}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
