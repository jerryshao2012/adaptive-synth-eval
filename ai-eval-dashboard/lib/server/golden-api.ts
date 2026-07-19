import { NextResponse } from "next/server";

import {
  GoldenConflictError,
  GoldenNotFoundError,
  GoldenValidationError,
} from "@/lib/server/golden-catalog";
import { GOLDEN_METRIC_KEYS } from "@/lib/golden-metrics";
import type { GoldenMetricKey } from "@/types/evaluation";

export function goldenErrorResponse(error: unknown): NextResponse {
  const message = error instanceof Error ? error.message : "Golden dataset operation failed.";
  if (error instanceof GoldenValidationError) {
    return NextResponse.json({ error: message, code: error.code }, { status: 422 });
  }
  if (error instanceof GoldenConflictError) {
    return NextResponse.json({ error: message, code: error.code }, { status: 409 });
  }
  if (error instanceof GoldenNotFoundError) {
    return NextResponse.json({ error: message, code: error.code }, { status: 404 });
  }
  return NextResponse.json({ error: message, code: "internal_error" }, { status: 500 });
}

export async function readJsonObject(
  request: Request
): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    throw new GoldenValidationError("Invalid JSON body.");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new GoldenValidationError("JSON body must be an object.");
  }
  return body as Record<string, unknown>;
}

export function assertExactKeys(
  body: Record<string, unknown>,
  allowed: readonly string[]
): void {
  const extra = Object.keys(body).filter((key) => !allowed.includes(key));
  if (extra.length) {
    throw new GoldenValidationError(`Unexpected field '${extra[0]}'.`);
  }
}

export function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new GoldenValidationError(`${label} is required.`);
  }
  return value.trim();
}

export function optionalString(value: unknown, label: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") {
    throw new GoldenValidationError(`${label} must be a string.`);
  }
  return value.trim();
}

export function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new GoldenValidationError(`${label} must be an array of strings.`);
  }
  return value.map((entry) => entry.trim()).filter(Boolean);
}

export function metricArray(value: unknown): GoldenMetricKey[] {
  const values = stringArray(value, "dimensions");
  const supported = new Set<string>(GOLDEN_METRIC_KEYS);
  for (const metric of values) {
    if (!supported.has(metric)) {
      throw new GoldenValidationError(`Unknown golden metric dimension '${metric}'.`);
    }
  }
  return values as GoldenMetricKey[];
}

export function revision(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 1) {
    throw new GoldenValidationError("expectedRevision must be a positive integer.");
  }
  return Number(value);
}

export function queryList(value: string | null): string[] | undefined {
  const result = value?.split(",").map((entry) => entry.trim()).filter(Boolean);
  return result?.length ? result : undefined;
}

export function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new GoldenValidationError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

export function exportFormat(value: string | null): "jsonl" | "csv" {
  const format = value ?? "jsonl";
  if (format !== "jsonl" && format !== "csv") {
    throw new GoldenValidationError("format must be 'jsonl' or 'csv'.");
  }
  return format;
}
