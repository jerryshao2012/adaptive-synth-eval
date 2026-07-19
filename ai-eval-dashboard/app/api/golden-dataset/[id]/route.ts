import { NextRequest, NextResponse } from "next/server";
import {
  getDataset,
  LegacyDatasetIdError,
  updateDataset,
} from "@/lib/server/golden-datasets";

export const runtime = "nodejs";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  try {
    const dataset = await getDataset(id);
    if (!dataset) {
      return NextResponse.json({ error: "Dataset not found." }, { status: 404 });
    }
    return NextResponse.json(dataset);
  } catch (error) {
    if (error instanceof LegacyDatasetIdError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    const message =
      error instanceof Error ? error.message : "Failed to load dataset.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  let updates: Record<string, unknown>;
  try {
    updates = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  try {
    const updated = await updateDataset(id, updates);
    if (!updated) {
      return NextResponse.json(
        { error: "Dataset not found." },
        { status: 404 }
      );
    }
    return NextResponse.json(updated);
  } catch (error) {
    if (error instanceof LegacyDatasetIdError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    const message =
      error instanceof Error ? error.message : "Failed to update dataset.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
