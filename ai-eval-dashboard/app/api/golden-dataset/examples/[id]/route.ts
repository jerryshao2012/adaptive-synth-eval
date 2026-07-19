import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  readJsonObject,
  stringArray,
} from "@/lib/server/golden-api";
import { GoldenNotFoundError, goldenCatalog } from "@/lib/server/golden-catalog";

export const runtime = "nodejs";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const example = await goldenCatalog.getExample(id);
    if (!example) throw new GoldenNotFoundError(`Example '${id}' was not found.`);
    return NextResponse.json(example);
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await readJsonObject(request);
    assertExactKeys(body, ["tags"]);
    return NextResponse.json(
      await goldenCatalog.updateExampleMetadata(id, {
        tags: stringArray(body.tags, "tags"),
      })
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
