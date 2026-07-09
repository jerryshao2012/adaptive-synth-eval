"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { METRIC_THRESHOLDS } from "@/lib/metrics";
import type { ReviewStats } from "@/types/evaluation";

interface AgreementChartProps {
  stats: ReviewStats | undefined;
  isLoading: boolean;
}

function barColor(agreement: number): string {
  if (agreement >= 80) return "hsl(142 71% 35%)"; // emerald
  if (agreement >= 60) return "hsl(43 74% 56%)"; // amber
  return "hsl(0 80% 55%)"; // red
}

export function AgreementChart({ stats, isLoading }: AgreementChartProps) {
  const data = useMemo(() => {
    if (!stats?.perMetricAgreement) return [];
    return Object.entries(stats.perMetricAgreement)
      .filter(([key]) => METRIC_THRESHOLDS[key])
      .map(([key, agreement]) => ({
        name: METRIC_THRESHOLDS[key].label,
        agreement,
      }))
      .sort((a, b) => a.agreement - b.agreement);
  }, [stats]);

  if (isLoading || !stats) {
    return null;
  }

  if (data.length === 0) {
    return null;
  }

  return (
    <Card className="border-border bg-card mb-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold text-foreground">
          Inter-Rater Agreement by Metric
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          % of reviews where human score = AI score (±5 points). Overall:{" "}
          <span className="font-medium text-foreground tabular-nums">
            {stats.averageAgreement}%
          </span>
        </p>
      </CardHeader>
      <CardContent>
        <div className="h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 4, right: 24, bottom: 4, left: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(210 20% 78%)"
                strokeOpacity={0.4}
                horizontal
              />
              <XAxis
                type="number"
                domain={[0, 100]}
                tick={{ fontSize: 11, fill: "hsl(210 12% 35%)" }}
                tickLine={false}
                axisLine={{ stroke: "hsl(210 18% 72%)" }}
                tickFormatter={(v) => `${v}%`}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 11, fill: "hsl(210 12% 35%)" }}
                tickLine={false}
                axisLine={{ stroke: "hsl(210 18% 72%)" }}
                width={160}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0].payload as {
                    name: string;
                    agreement: number;
                  };
                  return (
                    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-lg">
                      <p className="font-medium text-foreground">
                        {point.name}
                      </p>
                      <p className="text-muted-foreground">
                        Agreement:{" "}
                        <span className="font-semibold text-foreground tabular-nums">
                          {point.agreement}%
                        </span>
                      </p>
                    </div>
                  );
                }}
              />
              <Bar dataKey="agreement" radius={[0, 4, 4, 0]}>
                {data.map((entry, index) => (
                  <Cell key={index} fill={barColor(entry.agreement)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
