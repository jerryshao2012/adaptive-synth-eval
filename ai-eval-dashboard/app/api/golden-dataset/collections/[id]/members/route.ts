import { NextRequest, NextResponse } from "next/server";

import {
  assertExactKeys,
  goldenErrorResponse,
  objectValue,
  optionalString,
  readJsonObject,
  requiredString,
  revision,
} from "@/lib/server/golden-api";
import { GoldenValidationError, goldenCatalog } from "@/lib/server/golden-catalog";
import type { GoldenAnnotation, GoldenMetricKey } from "@/types/evaluation";

export const runtime = "nodejs";

type MembershipService = Partial<
  Pick<typeof goldenCatalog, "upsertMembership" | "upsertMemberships">
>;

function parseAnnotations(value: unknown) {
  const raw = objectValue(value ?? {}, "annotations");
  const annotations: Partial<Record<GoldenMetricKey, GoldenAnnotation>> = {};
  for (const [metric, candidate] of Object.entries(raw)) {
    const annotation = objectValue(candidate, `annotations.${metric}`);
    const expectedStatus = requiredString(
      annotation.expectedStatus,
      `annotations.${metric}.expectedStatus`
    );
    if (!["pass", "warn", "fail"].includes(expectedStatus)) {
      throw new GoldenValidationError(`Invalid expected status for '${metric}'.`);
    }
    const expectedScore = annotation.expectedScore;
    if (expectedScore !== undefined && typeof expectedScore !== "number") {
      throw new GoldenValidationError(`Expected score for '${metric}' must be a number.`);
    }
    annotations[metric as GoldenMetricKey] = {
      expectedStatus: expectedStatus as GoldenAnnotation["expectedStatus"],
      expectedScore,
      rationale: optionalString(annotation.rationale, "rationale") ?? "",
      reviewerId: optionalString(annotation.reviewerId, "reviewerId") ?? "",
      reviewedAt: optionalString(annotation.reviewedAt, "reviewedAt") ?? "",
    };
  }
  return annotations;
}

export async function handleMembersPost(
  request: NextRequest,
  collectionId: string,
  service: MembershipService = goldenCatalog
) {
  try {
    const body = await readJsonObject(request);
    assertExactKeys(body, [
      "expectedRevision",
      "exampleId",
      "annotations",
      "weight",
      "notes",
      "members",
    ]);
    const expectedRevision = revision(body.expectedRevision);
    if (body.members !== undefined) {
      if (!Array.isArray(body.members)) {
        throw new GoldenValidationError("members must be an array.");
      }
      if (!service.upsertMemberships) {
        throw new GoldenValidationError("Bulk membership updates are unavailable.");
      }
      const members = body.members.map((candidate, index) => {
        const member = objectValue(candidate, `members.${index}`);
        assertExactKeys(member, ["exampleId", "annotations", "weight", "notes"]);
        if (member.weight !== undefined && typeof member.weight !== "number") {
          throw new GoldenValidationError(`members.${index}.weight must be a number.`);
        }
        return {
          exampleId: requiredString(member.exampleId, `members.${index}.exampleId`),
          ...(member.annotations === undefined
            ? {}
            : { annotations: parseAnnotations(member.annotations) }),
          ...(member.weight === undefined ? {} : { weight: member.weight as number }),
          ...(member.notes === undefined
            ? {}
            : { notes: optionalString(member.notes, `members.${index}.notes`) ?? "" }),
        };
      });
      return NextResponse.json(
        await service.upsertMemberships(collectionId, {
          expectedRevision,
          members,
        })
      );
    }
    if (!service.upsertMembership) {
      throw new GoldenValidationError("Membership updates are unavailable.");
    }
    if (body.weight !== undefined && typeof body.weight !== "number") {
      throw new GoldenValidationError("weight must be a number.");
    }
    const collection = await service.upsertMembership(collectionId, {
      expectedRevision,
      exampleId: requiredString(body.exampleId, "exampleId"),
      ...(body.annotations === undefined
        ? {}
        : { annotations: parseAnnotations(body.annotations) }),
      ...(body.weight === undefined ? {} : { weight: body.weight }),
      ...(body.notes === undefined
        ? {}
        : { notes: optionalString(body.notes, "notes") ?? "" }),
    });
    return NextResponse.json(collection);
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  return handleMembersPost(request, id);
}

type RemoveMembershipsService = Pick<typeof goldenCatalog, "removeMemberships">;

export async function handleMembersDelete(
  request: NextRequest,
  collectionId: string,
  service: RemoveMembershipsService = goldenCatalog
) {
  try {
    const body = await readJsonObject(request);
    assertExactKeys(body, ["expectedRevision", "exampleIds"]);
    if (
      !Array.isArray(body.exampleIds) ||
      body.exampleIds.some((exampleId) => typeof exampleId !== "string")
    ) {
      throw new GoldenValidationError("exampleIds must be an array of strings.");
    }
    return NextResponse.json(
      await service.removeMemberships(collectionId, {
        expectedRevision: revision(body.expectedRevision),
        exampleIds: body.exampleIds.map((exampleId) => exampleId.trim()),
      })
    );
  } catch (error) {
    return goldenErrorResponse(error);
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  return handleMembersDelete(request, id);
}
