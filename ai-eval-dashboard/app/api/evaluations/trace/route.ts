import { NextRequest, NextResponse } from "next/server";

import { getMonitoringTraceDetails } from "@/lib/server/monitoring";
import type { MetricPointIdentity } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("runId");
  const conversationId = searchParams.get("conversationId") || undefined;
  const turnId = searchParams.get("turnId");
  const timestamp = searchParams.get("timestamp");
  const metricGroup = searchParams.get("metricGroup") as
    | "safety"
    | "performance"
    | "reliability"
    | null;
  const metricKey = searchParams.get("metricKey");

  if (!runId || !turnId || !timestamp || !metricGroup || !metricKey) {
    return NextResponse.json(
      {
        error:
          "runId, turnId, timestamp, metricGroup, and metricKey query parameters are required.",
      },
      { status: 400 }
    );
  }

  if (!["safety", "performance", "reliability"].includes(metricGroup)) {
    return NextResponse.json(
      { error: "metricGroup must be 'safety', 'performance', or 'reliability'." },
      { status: 400 }
    );
  }

  const point: MetricPointIdentity = {
    runId,
    conversationId,
    turnId,
    timestamp,
    metricGroup,
    metricKey,
  };

  const details = await getMonitoringTraceDetails(point);
  if (!details) {
    return NextResponse.json(
      { error: `Run '${runId}' was not found.` },
      { status: 404 }
    );
  }

  return NextResponse.json(details);
}
