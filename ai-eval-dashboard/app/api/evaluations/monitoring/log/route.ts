import { NextRequest, NextResponse } from "next/server";

import { readMonitoringLogTail } from "@/lib/server/monitoring-launch";
import {
  RunNotFoundError,
  RunPathValidationError,
} from "@/lib/server/run-paths";
import type { MonitoringLogResponse } from "@/types/evaluation";

export const runtime = "nodejs";

type ReadMonitoringLogFn = (runId: string) => Promise<MonitoringLogResponse>;

export async function handleMonitoringLogGet(
  request: NextRequest,
  readLog: ReadMonitoringLogFn = readMonitoringLogTail
) {
  const runId = new URL(request.url).searchParams.get("runId");
  if (!runId) {
    return NextResponse.json(
      { error: "runId query parameter is required." },
      { status: 400 }
    );
  }

  try {
    return NextResponse.json(await readLog(runId));
  } catch (error) {
    if (error instanceof RunPathValidationError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    if (error instanceof RunNotFoundError) {
      return NextResponse.json({ error: error.message }, { status: 404 });
    }
    throw error;
  }
}

export async function GET(request: NextRequest) {
  return handleMonitoringLogGet(request);
}
