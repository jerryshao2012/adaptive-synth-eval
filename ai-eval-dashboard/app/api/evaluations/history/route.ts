import { NextRequest, NextResponse } from "next/server";
import { generateMockEvaluations } from "@/lib/mock-data";
import { getMonitoringEvaluations } from "@/lib/server/monitoring";

const BACKEND_URL =
  process.env.EVAL_BACKEND_URL || "http://localhost:8000";

export const runtime = "nodejs";

function parseLimit(value: string | null): number | null | undefined {
  if (value === null) return 2000;
  if (value === "all") return null;
  if (!/^\d+$/.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const rawLimit = searchParams.get("limit");
  const limit = parseLimit(rawLimit);
  const runId = searchParams.get("runId");

  if (limit === undefined) {
    return NextResponse.json(
      { error: "limit must be a positive integer or 'all'." },
      { status: 400 }
    );
  }
  if (limit === null && !runId) {
    return NextResponse.json(
      { error: "limit=all is supported only for local run history." },
      { status: 400 }
    );
  }

  if (runId) {
    const data = await getMonitoringEvaluations(
      runId,
      from || undefined,
      to || undefined,
      limit
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

  // `limit=all` is rejected above for requests without a local run ID, so the
  // mock and external-backend paths retain their numeric limit contract.
  const numericLimit = limit ?? 2000;

  // If no backend URL configured, return mock data
  if (!process.env.EVAL_BACKEND_URL) {
    const evaluations = generateMockEvaluations(
      from || undefined,
      to || undefined,
      numericLimit
    );
    return NextResponse.json({
      evaluations,
      profilePeriods: [],
      total: evaluations.length,
      from: from || "",
      to: to || "",
    });
  }

  // Proxy to real backend
  try {
    const backendParams = new URLSearchParams({ limit: String(numericLimit) });
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
    return NextResponse.json({
      ...data,
      profilePeriods: Array.isArray(data?.profilePeriods) ? data.profilePeriods : [],
    });
  } catch (err) {
    console.error("Backend fetch failed, falling back to mock:", err);
    const evaluations = generateMockEvaluations(
      from || undefined,
      to || undefined,
      numericLimit
    );
    return NextResponse.json({
      evaluations,
      profilePeriods: [],
      total: evaluations.length,
      from: from || "",
      to: to || "",
    });
  }
}
