import { NextRequest, NextResponse } from "next/server";

import { goldenErrorResponse } from "@/lib/server/golden-api";
import { goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    return NextResponse.json(await goldenCatalog.upgradeLegacyDataset(id), {
      status: 201,
    });
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
