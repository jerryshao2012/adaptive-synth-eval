import { NextRequest, NextResponse } from "next/server";
import { generateMockEvaluations } from "@/lib/mock-data";
import { getMonitoringEvaluations } from "@/lib/server/monitoring";

const BACKEND_URL =
  process.env.EVAL_BACKEND_URL || "http://localhost:8000";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const limit = searchParams.get("limit") || "2000";
  const runId = searchParams.get("runId");

  if (runId) {
    const data = await getMonitoringEvaluations(
      runId,
      from || undefined,
      to || undefined,
      parseInt(limit, 10)
    );
    if (!data) {
      return NextResponse.json(
        {
          error: `No monitoring scores found for run '${runId}'.`,
        },
        { status: 404 }
      );
    }
    return NextResponse.json(data);
  }

  // If no backend URL configured, return mock data
  if (!process.env.EVAL_BACKEND_URL) {
    const evaluations = generateMockEvaluations(
      from || undefined,
      to || undefined,
      parseInt(limit, 10)
    );
    return NextResponse.json({
      evaluations,
      total: evaluations.length,
      from: from || "",
      to: to || "",
    });
  }

  // Proxy to real backend
  try {
    const backendParams = new URLSearchParams({ limit });
    if (from) backendParams.set("from", from);
    if (to) backendParams.set("to", to);

    const res = await fetch(
      `${BACKEND_URL}/api/evaluations/history?${backendParams}`,
      {
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(15000),
      }
    );

    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    console.error("Backend fetch failed, falling back to mock:", err);
    const evaluations = generateMockEvaluations(
      from || undefined,
      to || undefined,
      parseInt(limit, 10)
    );
    return NextResponse.json({
      evaluations,
      total: evaluations.length,
      from: from || "",
      to: to || "",
    });
  }
}
