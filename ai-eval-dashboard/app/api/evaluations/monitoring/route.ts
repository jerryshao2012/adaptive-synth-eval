import { NextRequest, NextResponse } from "next/server";

import {
  getMonitoringStatus,
  startMonitoringRun,
} from "@/lib/server/monitoring";
import type { MonitoringStartRequest } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const runId = searchParams.get("runId");

  if (!runId) {
    return NextResponse.json(
      { error: "runId query parameter is required." },
      { status: 400 }
    );
  }

  const status = await getMonitoringStatus(runId);
  if (!status) {
    return NextResponse.json(
      { error: `Run '${runId}' was not found.` },
      { status: 404 }
    );
  }

  return NextResponse.json(status);
}

export async function POST(request: NextRequest) {
  let payload: MonitoringStartRequest;
  try {
    payload = (await request.json()) as MonitoringStartRequest;
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body." },
      { status: 400 }
    );
  }

  if (!payload?.runId || !payload?.metricVersion || !payload?.action) {
    return NextResponse.json(
      { error: "runId, metricVersion, and action are required." },
      { status: 400 }
    );
  }
  if (!["start", "continue"].includes(payload.action)) {
    return NextResponse.json(
      { error: "action must be either 'start' or 'continue'." },
      { status: 400 }
    );
  }
  if (
    payload.sampleSize !== undefined &&
    (!Number.isFinite(Number(payload.sampleSize)) || Number(payload.sampleSize) <= 0)
  ) {
    return NextResponse.json(
      { error: "sampleSize must be a positive number." },
      { status: 400 }
    );
  }
  if (
    payload.intervalMinutes !== undefined &&
    (!Number.isFinite(Number(payload.intervalMinutes)) || Number(payload.intervalMinutes) <= 0)
  ) {
    return NextResponse.json(
      { error: "intervalMinutes must be a positive number." },
      { status: 400 }
    );
  }

  try {
    const response = await startMonitoringRun(payload);
    return NextResponse.json(response, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to start monitoring run.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
