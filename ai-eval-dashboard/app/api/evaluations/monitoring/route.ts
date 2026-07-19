import { NextRequest, NextResponse } from "next/server";

import {
  getMonitoringStatus,
  startMonitoringRun,
} from "@/lib/server/monitoring";
import {
  MonitoringRequestValidationError,
  parseMonitoringStartRequest,
} from "@/lib/monitoring-config";
import type {
  MonitoringStartRequest,
  MonitoringStartResponse,
} from "@/types/evaluation";

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

type StartMonitoringFn = (
  request: MonitoringStartRequest
) => Promise<MonitoringStartResponse>;

export async function handleMonitoringPost(
  request: NextRequest,
  startFn: StartMonitoringFn
) {
  let value: unknown;
  try {
    value = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body." },
      { status: 400 }
    );
  }

  let payload: MonitoringStartRequest;
  try {
    payload = parseMonitoringStartRequest(value);
  } catch (error) {
    if (!(error instanceof MonitoringRequestValidationError)) {
      throw error;
    }
    return NextResponse.json(
      { error: error.message },
      { status: 400 }
    );
  }

  try {
    const response = await startFn(payload);
    return NextResponse.json(response, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to start monitoring run.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  return handleMonitoringPost(request, startMonitoringRun);
}
