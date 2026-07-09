import { NextResponse } from "next/server";

import { listRunSummaries } from "@/lib/server/monitoring";

export const runtime = "nodejs";

export async function GET() {
  const runs = await listRunSummaries();
  return NextResponse.json({ runs });
}
