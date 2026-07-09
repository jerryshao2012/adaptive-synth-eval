import { NextRequest, NextResponse } from "next/server";
import { listDatasets, createDataset } from "@/lib/server/golden-datasets";

export const runtime = "nodejs";

export async function GET() {
  try {
    const datasets = await listDatasets();
    return NextResponse.json(datasets);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to list datasets.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  let body: { name?: string; version?: string; filters?: Record<string, unknown> };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!body?.name || !body?.version) {
    return NextResponse.json(
      { error: "name and version are required." },
      { status: 400 }
    );
  }

  try {
    const dataset = await createDataset({
      name: body.name,
      version: body.version,
      filters: (body.filters || {}) as { runIds?: string[] },
    });
    return NextResponse.json(dataset, { status: 201 });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to create dataset.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
