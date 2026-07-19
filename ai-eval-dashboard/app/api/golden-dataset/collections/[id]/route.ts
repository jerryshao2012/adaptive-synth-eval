import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  metricArray,
  optionalString,
  readJsonObject,
  revision,
  stringArray,
} from "@/lib/server/golden-api";
import { GoldenNotFoundError, GoldenValidationError, goldenCatalog } from "@/lib/server/golden-catalog";
import type { GoldenCollection } from "@/types/evaluation";

export const runtime = "nodejs";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const collection = await goldenCatalog.getCollection(id);
    if (!collection) throw new GoldenNotFoundError(`Collection '${id}' was not found.`);
    const versions = await goldenCatalog.listVersions(id);
    return NextResponse.json({ ...collection, versions });
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
    assertExactKeys(body, [
      "expectedRevision",
      "name",
      "description",
      "dimensions",
      "tags",
      "status",
    ]);
    if (
      body.status !== undefined &&
      !["draft", "published", "archived"].includes(String(body.status))
    ) {
      throw new GoldenValidationError("Invalid collection status.");
    }
    return NextResponse.json(
      await goldenCatalog.updateCollection(id, {
        expectedRevision: revision(body.expectedRevision),
        name: optionalString(body.name, "name"),
        description: optionalString(body.description, "description"),
        dimensions: body.dimensions === undefined ? undefined : metricArray(body.dimensions),
        tags: body.tags === undefined ? undefined : stringArray(body.tags, "tags"),
        status: body.status as GoldenCollection["status"] | undefined,
      })
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}
