import { createHash, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { GOLDEN_METRIC_KEYS } from "@/lib/golden-metrics";
import { getMonitoringEvaluations } from "@/lib/server/monitoring";
import { getHumanReviews } from "@/lib/server/reviews";
import type {
  GoldenAnnotation,
  GoldenCollection,
  GoldenDataset,
  GoldenDatasetVersion,
  GoldenExample,
  GoldenExampleContent,
  GoldenMetricKey,
  GoldenReviewSnapshot,
  GoldenSourceRef,
} from "@/types/evaluation";

const DEFAULT_REPO_ROOT = path.resolve(process.cwd(), "..");
const FILE_LOCK_TIMEOUT_MS = 5_000;
const FILE_LOCK_POLL_MS = 10;

const metricKeySet = new Set<string>(GOLDEN_METRIC_KEYS);

export class GoldenValidationError extends Error {
  readonly code = "validation_error";

  constructor(message: string) {
    super(message);
    this.name = "GoldenValidationError";
  }
}

export class GoldenConflictError extends Error {
  readonly code = "conflict";

  constructor(message: string) {
    super(message);
    this.name = "GoldenConflictError";
  }
}

export class GoldenNotFoundError extends Error {
  readonly code = "not_found";

  constructor(message: string) {
    super(message);
    this.name = "GoldenNotFoundError";
  }
}

export interface GoldenExampleImport {
  content: GoldenExampleContent;
  source: GoldenSourceRef;
  review: GoldenReviewSnapshot;
  tags?: string[];
}

export interface GoldenExampleFilters {
  search?: string;
  tags?: string[];
  dimensions?: GoldenMetricKey[];
  collectionId?: string;
  runId?: string;
}

export interface GoldenCollectionFilters {
  search?: string;
  tags?: string[];
  dimensions?: GoldenMetricKey[];
  status?: GoldenCollection["status"];
}

export interface LegacyRecordRef {
  runId: string;
  conversationId: string;
  turnId: string;
}

export type LegacyRecordResolver = (
  ref: LegacyRecordRef
) => Promise<GoldenExampleImport | null>;

export interface GoldenCatalogOptions {
  repoRoot?: string;
  now?: () => Date;
  resolveLegacyRecord?: LegacyRecordResolver;
}

export interface GoldenExport {
  content: string;
  filename: string;
  contentType: string;
  preview: boolean;
}

interface CollectionUpdate {
  expectedRevision: number;
  name?: string;
  description?: string;
  dimensions?: GoldenMetricKey[];
  tags?: string[];
  status?: GoldenCollection["status"];
}

interface MembershipUpdate {
  expectedRevision: number;
  exampleId: string;
  annotations?: GoldenCollection["memberships"][number]["annotations"];
  weight?: number;
  notes?: string;
}

interface LegacyDatasetShape extends GoldenDataset {
  schemaVersion?: never;
}

function normalizeText(value: string): string {
  return value.replace(/\r\n?/g, "\n").replace(/\n+$/u, "");
}

function normalizeContent(content: GoldenExampleContent): GoldenExampleContent {
  const normalized: GoldenExampleContent = {
    userText: normalizeText(content.userText),
    responseText: normalizeText(content.responseText),
  };
  for (const key of [
    "conversationContext",
    "referenceContext",
    "referenceAnswer",
  ] as const) {
    const value = content[key];
    if (typeof value === "string" && value.length > 0) {
      normalized[key] = normalizeText(value);
    }
  }
  return normalized;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stableValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, stableValue(entry)])
    );
  }
  return value;
}

function stableJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

function sha256(value: unknown): string {
  return createHash("sha256").update(stableJson(value)).digest("hex");
}

function sourceKey(source: Pick<GoldenSourceRef, "runId" | "conversationId" | "turnId">) {
  return `${source.runId}\u0000${source.conversationId}\u0000${source.turnId}`;
}

function contentTokens(content: GoldenExampleContent): Set<string> {
  const tokens = Object.values(content)
    .join(" ")
    .toLocaleLowerCase()
    .match(/[\p{L}\p{N}]+/gu);
  return new Set(tokens ?? []);
}

function contentSimilarity(left: GoldenExampleContent, right: GoldenExampleContent): number {
  const leftTokens = contentTokens(left);
  const rightTokens = contentTokens(right);
  if (leftTokens.size < 4 || rightTokens.size < 4) return 0;
  const intersection = [...leftTokens].filter((token) => rightTokens.has(token)).length;
  const union = new Set([...leftTokens, ...rightTokens]).size;
  return union ? intersection / union : 0;
}

function normalizeTags(tags: string[] | undefined): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const raw of tags ?? []) {
    const tag = raw.trim();
    const key = tag.toLocaleLowerCase();
    if (!tag || seen.has(key)) continue;
    seen.add(key);
    result.push(tag);
  }
  return result;
}

function mergeTags(existing: string[], incoming: string[] | undefined): string[] {
  const result = [...existing];
  const seen = new Set(existing.map((tag) => tag.toLocaleLowerCase()));
  for (const tag of normalizeTags(incoming)) {
    const key = tag.toLocaleLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      result.push(tag);
    }
  }
  return result;
}

function validateSafeSegment(value: string, label: string): string {
  const normalized = value.trim();
  if (
    !normalized ||
    normalized === "." ||
    normalized === ".." ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(normalized)
  ) {
    throw new GoldenValidationError(`${label} must be one safe path segment.`);
  }
  return normalized;
}

function validateVersion(version: string): string {
  const normalized = version.trim();
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/u.test(normalized)) {
    throw new GoldenValidationError(
      "version must use semantic versioning such as 1.0.0."
    );
  }
  return normalized;
}

function validateDimensions(dimensions: GoldenMetricKey[]): GoldenMetricKey[] {
  const unique: GoldenMetricKey[] = [];
  const seen = new Set<string>();
  for (const dimension of dimensions) {
    if (!metricKeySet.has(dimension)) {
      throw new GoldenValidationError(`Unknown golden metric dimension '${dimension}'.`);
    }
    if (!seen.has(dimension)) {
      seen.add(dimension);
      unique.push(dimension);
    }
  }
  if (unique.length === 0) {
    throw new GoldenValidationError("At least one metric dimension is required.");
  }
  return unique;
}

function validateAnnotation(metric: string, annotation: GoldenAnnotation): void {
  if (!metricKeySet.has(metric)) {
    throw new GoldenValidationError(`Unknown golden metric dimension '${metric}'.`);
  }
  if (!["pass", "warn", "fail"].includes(annotation.expectedStatus)) {
    throw new GoldenValidationError(`Invalid expected status for '${metric}'.`);
  }
  if (
    annotation.expectedScore !== undefined &&
    (!Number.isFinite(annotation.expectedScore) ||
      annotation.expectedScore < 0 ||
      annotation.expectedScore > 100)
  ) {
    throw new GoldenValidationError(
      `Expected score for '${metric}' must be between 0 and 100.`
    );
  }
}

function validateExampleImportInput(input: GoldenExampleImport): void {
  if (input.review.reviewStatus !== "approved") {
    throw new GoldenValidationError("Only approved human reviews can be imported.");
  }
  if (!input.content.userText || !input.content.responseText) {
    throw new GoldenValidationError("userText and responseText are required.");
  }
  for (const field of ["runId", "conversationId", "turnId", "reviewId"] as const) {
    if (!input.source[field]?.trim()) {
      throw new GoldenValidationError(`source.${field} is required.`);
    }
  }
}

async function atomicWriteJson(filePath: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, "utf-8");
  await fs.rename(temporaryPath, filePath);
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

async function withFileLock<T>(lockPath: string, operation: () => Promise<T>): Promise<T> {
  await fs.mkdir(path.dirname(lockPath), { recursive: true });
  const token = randomUUID();
  const intentFile = `${path.basename(lockPath)}.${process.pid}.${token}.intent`;
  const intentPath = path.join(path.dirname(lockPath), intentFile);
  const owner = {
    token,
    pid: process.pid,
    createdAt: new Date().toISOString(),
    intentFile,
  };
  const deadline = Date.now() + FILE_LOCK_TIMEOUT_MS;
  await fs.writeFile(intentPath, JSON.stringify(owner), {
    encoding: "utf-8",
    flag: "wx",
  });
  let acquired = false;
  let released = false;
  try {
    while (!acquired) {
      try {
        await fs.link(intentPath, lockPath);
        acquired = true;
        break;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      }
      let current: { token: string; pid: number; intentFile: string } | null = null;
      try {
        const candidate = JSON.parse(await fs.readFile(lockPath, "utf-8")) as {
          token?: unknown;
          pid?: unknown;
          intentFile?: unknown;
        };
        if (
          typeof candidate.token === "string" &&
          typeof candidate.pid === "number" &&
          Number.isInteger(candidate.pid) &&
          candidate.pid > 0 &&
          typeof candidate.intentFile === "string"
        ) {
          current = candidate as { token: string; pid: number; intentFile: string };
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
        if (!(error instanceof SyntaxError)) throw error;
      }
      if (current && !processIsAlive(current.pid)) {
        const staleIntentPath = path.join(path.dirname(lockPath), current.intentFile);
        let claimed = false;
        try {
          await fs.unlink(staleIntentPath);
          claimed = true;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
        if (claimed) {
          await fs.unlink(lockPath).catch((error) => {
            if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
          });
          continue;
        }
      }
      if (Date.now() >= deadline) {
        throw new GoldenConflictError(`Timed out waiting for golden dataset lock '${lockPath}'.`);
      }
      await new Promise((resolve) => setTimeout(resolve, FILE_LOCK_POLL_MS));
    }
    try {
      return await operation();
    } finally {
      const current = JSON.parse(await fs.readFile(lockPath, "utf-8")) as {
        token?: string;
      };
      if (current.token !== token) {
        throw new GoldenConflictError("Golden dataset lock ownership changed before release.");
      }
      await fs.unlink(lockPath);
      released = true;
    }
  } finally {
    if (!acquired || released) {
      await fs.unlink(intentPath).catch((error) => {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      });
    }
  }
}

async function readJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf-8")) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new GoldenValidationError(`Malformed golden artifact '${filePath}'.`);
  }
}

async function readJsonDirectory<T>(directory: string): Promise<T[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(directory);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  const records: T[] = [];
  for (const name of entries.filter((entry) => entry.endsWith(".json")).sort()) {
    const record = await readJson<T>(path.join(directory, name));
    if (record) records.push(record);
  }
  return records;
}

function csvEscape(value: unknown): string {
  const text = String(value ?? "");
  return /[,"\n]/u.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function versionFilename(name: string, version: string, format: "jsonl" | "csv") {
  return `${name.replace(/[^A-Za-z0-9._-]+/g, "_")}_${version}.${format}`;
}

function exportVersion(
  snapshot: GoldenDatasetVersion,
  format: "jsonl" | "csv",
  preview: boolean
): GoldenExport {
  const rows = snapshot.records.map((record) => ({
    collection_id: snapshot.collectionId,
    collection_name: snapshot.collectionName,
    dataset_version: snapshot.version,
    manifest_fingerprint: snapshot.manifestFingerprint,
    example_id: record.exampleId,
    content_fingerprint: record.contentFingerprint,
    ...record.content,
    tags: record.tags,
    annotations: record.annotations,
    weight: record.weight,
    notes: record.notes,
    source_refs: record.sourceRefs,
    preview,
  }));
  const filename = versionFilename(snapshot.collectionName, snapshot.version, format);
  if (format === "jsonl") {
    return {
      content: rows.map((row) => JSON.stringify(row)).join("\n"),
      filename,
      contentType: "application/x-jsonlines",
      preview,
    };
  }
  const headers = [
    "collection_id",
    "collection_name",
    "dataset_version",
    "manifest_fingerprint",
    "example_id",
    "content_fingerprint",
    "userText",
    "responseText",
    "conversationContext",
    "referenceContext",
    "referenceAnswer",
    "tags",
    "annotations",
    "weight",
    "notes",
    "source_refs",
    "preview",
  ];
  const content = [
    headers.join(","),
    ...rows.map((row) =>
      headers
        .map((header) => {
          const value = row[header as keyof typeof row];
          return csvEscape(typeof value === "object" ? JSON.stringify(value) : value);
        })
        .join(",")
    ),
  ].join("\n");
  return { content, filename, contentType: "text/csv", preview };
}

function annotationFromReview(
  metric: GoldenMetricKey,
  review: GoldenReviewSnapshot,
  source: GoldenSourceRef
): GoldenAnnotation | null {
  const score = review.safetyScores[metric] ?? review.performanceScores[metric];
  if (!score) return null;
  return {
    expectedStatus: score.status,
    expectedScore: score.humanScore,
    rationale: review.notes.trim() || "Migrated from an approved human review.",
    reviewerId: source.reviewerId,
    reviewedAt: source.reviewedAt,
  };
}

function normalizeLegacyVersion(version: string): string {
  const raw = version.trim().replace(/^v/u, "");
  if (/^\d+\.\d+\.\d+$/u.test(raw)) return raw;
  if (/^\d+\.\d+$/u.test(raw)) return `${raw}.0`;
  if (/^\d+$/u.test(raw)) return `${raw}.0.0`;
  return "1.0.0";
}

async function defaultLegacyResolver(ref: LegacyRecordRef): Promise<GoldenExampleImport | null> {
  const [evaluations, reviews] = await Promise.all([
    getMonitoringEvaluations(ref.runId),
    getHumanReviews(ref.runId),
  ]);
  const evaluation = evaluations?.evaluations.find(
    (entry) =>
      String(entry.turn_id) === ref.turnId &&
      String(entry.conversation_id ?? "") === ref.conversationId
  );
  const review = reviews.find(
    (entry) =>
      entry.turnId === ref.turnId && entry.conversationId === ref.conversationId
  );
  if (!evaluation || !review || review.reviewStatus !== "approved") return null;
  return {
    content: {
      userText: evaluation.user_text,
      responseText: evaluation.response_text,
    },
    source: {
      runId: ref.runId,
      conversationId: ref.conversationId,
      turnId: ref.turnId,
      reviewId: review.reviewId,
      reviewerId: review.reviewerId,
      reviewedAt: review.reviewedAt,
      evaluationFingerprint: evaluation.value_versions?.evaluation_fingerprint,
    },
    review: {
      reviewStatus: "approved",
      overallStatus: review.overallStatus,
      safetyScores: review.safetyScores,
      performanceScores: review.performanceScores,
      notes: review.notes,
      flags: review.flags,
    },
  };
}

export function createGoldenCatalog(options: GoldenCatalogOptions = {}) {
  const repoRoot = options.repoRoot ?? DEFAULT_REPO_ROOT;
  const root = path.join(repoRoot, "outputs", "golden_datasets");
  const examplesDirectory = path.join(root, "examples");
  const collectionsDirectory = path.join(root, "collections");
  const versionsDirectory = path.join(root, "versions");
  const locksDirectory = path.join(root, ".locks");
  const resolveLegacyRecord = options.resolveLegacyRecord ?? defaultLegacyResolver;
  const now = () => (options.now ?? (() => new Date()))().toISOString();
  const collectionLocks = new Map<string, Promise<void>>();

  async function withCollectionLock<T>(
    collectionId: string,
    operation: () => Promise<T>
  ): Promise<T> {
    const previous = collectionLocks.get(collectionId) ?? Promise.resolve();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const queued = previous.then(() => gate);
    collectionLocks.set(collectionId, queued);
    await previous;
    try {
      return await withFileLock(
        path.join(locksDirectory, `collection-${validateSafeSegment(collectionId, "collectionId")}.lock`),
        operation
      );
    } finally {
      release();
      if (collectionLocks.get(collectionId) === queued) {
        collectionLocks.delete(collectionId);
      }
    }
  }

  const examplePath = (exampleId: string) =>
    path.join(examplesDirectory, `${validateSafeSegment(exampleId, "exampleId")}.json`);
  const collectionPath = (collectionId: string) =>
    path.join(
      collectionsDirectory,
      `${validateSafeSegment(collectionId, "collectionId")}.json`
    );
  const versionPath = (collectionId: string, version: string) =>
    path.join(
      versionsDirectory,
      validateSafeSegment(collectionId, "collectionId"),
      `${validateVersion(version)}.json`
    );

  async function listExamples(filters: GoldenExampleFilters = {}): Promise<GoldenExample[]> {
    let examples = await readJsonDirectory<GoldenExample>(examplesDirectory);
    if (filters.collectionId) {
      const collection = await getCollection(filters.collectionId);
      if (!collection) return [];
      const ids = new Set(collection.memberships.map((member) => member.exampleId));
      examples = examples.filter((example) => ids.has(example.exampleId));
    }
    if (filters.runId) {
      examples = examples.filter((example) =>
        example.sourceRefs.some((source) => source.runId === filters.runId)
      );
    }
    if (filters.tags?.length) {
      const wanted = new Set(filters.tags.map((tag) => tag.toLocaleLowerCase()));
      examples = examples.filter((example) =>
        example.tags.some((tag) => wanted.has(tag.toLocaleLowerCase()))
      );
    }
    if (filters.dimensions?.length) {
      const wanted = new Set(filters.dimensions);
      const collectionIds = new Set(
        (await listCollections()).filter((collection) =>
          collection.dimensions.some((dimension) => wanted.has(dimension))
        ).map((collection) => collection.collectionId)
      );
      const memberIds = new Set<string>();
      for (const collection of await listCollections()) {
        if (!collectionIds.has(collection.collectionId)) continue;
        collection.memberships.forEach((member) => memberIds.add(member.exampleId));
      }
      examples = examples.filter((example) => memberIds.has(example.exampleId));
    }
    if (filters.search?.trim()) {
      const needle = filters.search.trim().toLocaleLowerCase();
      examples = examples.filter((example) =>
        [
          example.content.userText,
          example.content.responseText,
          ...example.tags,
          ...example.sourceRefs.map((source) => source.runId),
        ].some((value) => value.toLocaleLowerCase().includes(needle))
      );
    }
    return examples.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async function getExample(exampleId: string): Promise<GoldenExample | null> {
    return readJson<GoldenExample>(examplePath(exampleId));
  }

  async function importExample(input: GoldenExampleImport): Promise<GoldenExample> {
    return withFileLock(path.join(locksDirectory, "examples.lock"), () =>
      importExampleUnlocked(input)
    );
  }

  async function importExampleUnlocked(input: GoldenExampleImport): Promise<GoldenExample> {
    validateExampleImportInput(input);
    const content = normalizeContent(input.content);
    const contentFingerprint = sha256(content);
    const examples = await listExamples();
    const wantedSource = sourceKey(input.source);
    const bySource = examples.find((example) =>
      example.sourceRefs.some((source) => sourceKey(source) === wantedSource)
    );
    const byContent = examples.find(
      (example) => example.contentFingerprint === contentFingerprint
    );
    const existing = bySource ?? byContent;
    if (existing) {
      if (stableJson(existing.content) !== stableJson(content)) {
        throw new GoldenConflictError(
          "The source identity or content fingerprint is already attached to different content."
        );
      }
      const sources = [...existing.sourceRefs];
      if (!sources.some((source) => sourceKey(source) === wantedSource)) {
        sources.push(input.source);
      }
      const updated: GoldenExample = {
        ...existing,
        sourceRefs: sources,
        tags: mergeTags(existing.tags, input.tags),
        updatedAt: now(),
      };
      await atomicWriteJson(examplePath(updated.exampleId), updated);
      return updated;
    }
    const timestamp = now();
    const example: GoldenExample = {
      schemaVersion: 2,
      exampleId: randomUUID(),
      contentFingerprint,
      content,
      sourceRefs: [input.source],
      reviewSnapshot: input.review,
      tags: normalizeTags(input.tags),
      similarExampleIds: examples
        .filter((candidate) => contentSimilarity(candidate.content, content) >= 0.85)
        .map((candidate) => candidate.exampleId),
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    await atomicWriteJson(examplePath(example.exampleId), example);
    return example;
  }

  async function assertExampleImportsCompatible(
    inputs: GoldenExampleImport[]
  ): Promise<void> {
    const candidates = (await listExamples()).map((example) => ({
      content: example.content,
      contentFingerprint: example.contentFingerprint,
      sourceRefs: [...example.sourceRefs],
    }));
    for (const input of inputs) {
      validateExampleImportInput(input);
      const content = normalizeContent(input.content);
      const contentFingerprint = sha256(content);
      const wantedSource = sourceKey(input.source);
      const bySource = candidates.find((candidate) =>
        candidate.sourceRefs.some((source) => sourceKey(source) === wantedSource)
      );
      const byContent = candidates.find(
        (candidate) => candidate.contentFingerprint === contentFingerprint
      );
      const existing = bySource ?? byContent;
      if (existing) {
        if (stableJson(existing.content) !== stableJson(content)) {
          throw new GoldenConflictError(
            "The source identity or content fingerprint is already attached to different content."
          );
        }
        if (!existing.sourceRefs.some((source) => sourceKey(source) === wantedSource)) {
          existing.sourceRefs.push(input.source);
        }
      } else {
        candidates.push({
          content,
          contentFingerprint,
          sourceRefs: [input.source],
        });
      }
    }
  }

  async function updateExampleMetadata(
    exampleId: string,
    updates: { tags?: string[] }
  ): Promise<GoldenExample> {
    return withFileLock(path.join(locksDirectory, "examples.lock"), async () => {
      const existing = await getExample(exampleId);
      if (!existing) throw new GoldenNotFoundError(`Example '${exampleId}' was not found.`);
      const updated = {
        ...existing,
        tags: mergeTags(existing.tags, updates.tags),
        updatedAt: now(),
      };
      await atomicWriteJson(examplePath(exampleId), updated);
      return updated;
    });
  }

  async function listCollections(
    filters: GoldenCollectionFilters = {}
  ): Promise<GoldenCollection[]> {
    let collections = await readJsonDirectory<GoldenCollection>(collectionsDirectory);
    if (filters.status) {
      collections = collections.filter((collection) => collection.status === filters.status);
    }
    if (filters.tags?.length) {
      const wanted = new Set(filters.tags.map((tag) => tag.toLocaleLowerCase()));
      collections = collections.filter((collection) =>
        collection.tags.some((tag) => wanted.has(tag.toLocaleLowerCase()))
      );
    }
    if (filters.dimensions?.length) {
      const wanted = new Set(filters.dimensions);
      collections = collections.filter((collection) =>
        collection.dimensions.some((dimension) => wanted.has(dimension))
      );
    }
    if (filters.search?.trim()) {
      const needle = filters.search.trim().toLocaleLowerCase();
      collections = collections.filter((collection) =>
        [collection.name, collection.description, ...collection.tags].some((value) =>
          value.toLocaleLowerCase().includes(needle)
        )
      );
    }
    return collections.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async function getCollection(collectionId: string): Promise<GoldenCollection | null> {
    return readJson<GoldenCollection>(collectionPath(collectionId));
  }

  async function createCollection(input: {
    name: string;
    description: string;
    dimensions: GoldenMetricKey[];
    tags?: string[];
    legacyDatasetId?: string;
  }): Promise<GoldenCollection> {
    if (!input.name.trim()) throw new GoldenValidationError("Collection name is required.");
    const timestamp = now();
    const collection: GoldenCollection = {
      schemaVersion: 2,
      collectionId: randomUUID(),
      name: input.name.trim(),
      description: input.description.trim(),
      dimensions: validateDimensions(input.dimensions),
      tags: normalizeTags(input.tags),
      status: "draft",
      revision: 1,
      memberships: [],
      legacyDatasetId: input.legacyDatasetId,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    await atomicWriteJson(collectionPath(collection.collectionId), collection);
    return collection;
  }

  async function requireCollection(collectionId: string): Promise<GoldenCollection> {
    const collection = await getCollection(collectionId);
    if (!collection) {
      throw new GoldenNotFoundError(`Collection '${collectionId}' was not found.`);
    }
    return collection;
  }

  function assertRevision(collection: GoldenCollection, expectedRevision: number) {
    if (collection.revision !== expectedRevision) {
      throw new GoldenConflictError(
        `Collection revision changed from ${expectedRevision} to ${collection.revision}.`
      );
    }
  }

  async function updateCollection(
    collectionId: string,
    updates: CollectionUpdate
  ): Promise<GoldenCollection> {
    return withCollectionLock(collectionId, () =>
      updateCollectionUnlocked(collectionId, updates)
    );
  }

  async function updateCollectionUnlocked(
    collectionId: string,
    updates: CollectionUpdate
  ): Promise<GoldenCollection> {
    const collection = await requireCollection(collectionId);
    assertRevision(collection, updates.expectedRevision);
    const dimensions = updates.dimensions
      ? validateDimensions(updates.dimensions)
      : collection.dimensions;
    const updated: GoldenCollection = {
      ...collection,
      name: updates.name?.trim() || collection.name,
      description:
        updates.description === undefined
          ? collection.description
          : updates.description.trim(),
      dimensions,
      tags: updates.tags ? normalizeTags(updates.tags) : collection.tags,
      status: updates.status ?? collection.status,
      revision: collection.revision + 1,
      updatedAt: now(),
    };
    await atomicWriteJson(collectionPath(collectionId), updated);
    return updated;
  }

  async function upsertMembership(
    collectionId: string,
    input: MembershipUpdate
  ): Promise<GoldenCollection> {
    return upsertMemberships(collectionId, {
      expectedRevision: input.expectedRevision,
      members: [input],
    });
  }

  async function upsertMemberships(
    collectionId: string,
    input: {
      expectedRevision: number;
      members: Array<Omit<MembershipUpdate, "expectedRevision">>;
    }
  ): Promise<GoldenCollection> {
    return withCollectionLock(collectionId, () =>
      upsertMembershipsUnlocked(collectionId, input)
    );
  }

  async function upsertMembershipsUnlocked(
    collectionId: string,
    input: {
      expectedRevision: number;
      members: Array<Omit<MembershipUpdate, "expectedRevision">>;
    }
  ): Promise<GoldenCollection> {
    const collection = await requireCollection(collectionId);
    assertRevision(collection, input.expectedRevision);
    if (input.members.length === 0) {
      throw new GoldenValidationError("At least one membership is required.");
    }
    const incomingIds = new Set<string>();
    for (const member of input.members) {
      if (incomingIds.has(member.exampleId)) {
        throw new GoldenValidationError(
          `Example '${member.exampleId}' appears more than once in the membership request.`
        );
      }
      incomingIds.add(member.exampleId);
      if (!(await getExample(member.exampleId))) {
        throw new GoldenNotFoundError(`Example '${member.exampleId}' was not found.`);
      }
      for (const [metric, annotation] of Object.entries(member.annotations ?? {})) {
        if (!collection.dimensions.includes(metric as GoldenMetricKey)) {
          throw new GoldenValidationError(
            `Metric '${metric}' is not part of collection '${collection.name}'.`
          );
        }
        if (annotation) validateAnnotation(metric, annotation);
      }
      if (
        member.weight !== undefined &&
        (!Number.isFinite(member.weight) || member.weight <= 0)
      ) {
        throw new GoldenValidationError("Membership weight must be greater than zero.");
      }
    }
    const timestamp = now();
    const memberships = [...collection.memberships];
    for (const member of input.members) {
      const index = memberships.findIndex((entry) => entry.exampleId === member.exampleId);
      const existing = index >= 0 ? memberships[index] : undefined;
      const membership = {
        exampleId: member.exampleId,
        annotations: member.annotations ?? existing?.annotations ?? {},
        weight: member.weight ?? existing?.weight ?? 1,
        notes: member.notes ?? existing?.notes ?? "",
        addedAt: existing?.addedAt ?? timestamp,
        updatedAt: timestamp,
      };
      if (index >= 0) memberships[index] = membership;
      else memberships.push(membership);
    }
    const updated = {
      ...collection,
      memberships,
      revision: collection.revision + 1,
      updatedAt: timestamp,
    };
    await atomicWriteJson(collectionPath(collectionId), updated);
    return updated;
  }

  async function removeMembership(
    collectionId: string,
    exampleId: string,
    expectedRevision: number
  ): Promise<GoldenCollection> {
    return removeMemberships(collectionId, {
      expectedRevision,
      exampleIds: [exampleId],
    });
  }

  async function removeMemberships(
    collectionId: string,
    input: { expectedRevision: number; exampleIds: string[] }
  ): Promise<GoldenCollection> {
    return withCollectionLock(collectionId, () =>
      removeMembershipsUnlocked(collectionId, input)
    );
  }

  async function removeMembershipsUnlocked(
    collectionId: string,
    input: { expectedRevision: number; exampleIds: string[] }
  ): Promise<GoldenCollection> {
    const collection = await requireCollection(collectionId);
    assertRevision(collection, input.expectedRevision);
    if (input.exampleIds.length === 0) {
      throw new GoldenValidationError("At least one exampleId is required.");
    }
    const requested = new Set(input.exampleIds);
    if (requested.size !== input.exampleIds.length) {
      throw new GoldenValidationError("exampleIds cannot contain duplicates.");
    }
    const memberIds = new Set(collection.memberships.map((membership) => membership.exampleId));
    for (const exampleId of requested) {
      if (!memberIds.has(exampleId)) {
        throw new GoldenNotFoundError(
          `Example '${exampleId}' is not a member of collection '${collectionId}'.`
        );
      }
    }
    const memberships = collection.memberships.filter(
      (membership) => !requested.has(membership.exampleId)
    );
    const updated = {
      ...collection,
      memberships,
      revision: collection.revision + 1,
      updatedAt: now(),
    };
    await atomicWriteJson(collectionPath(collectionId), updated);
    return updated;
  }

  async function buildSnapshot(
    collection: GoldenCollection,
    version: string,
    publisherId: string,
    publishedAt: string
  ): Promise<GoldenDatasetVersion> {
    if (collection.memberships.length === 0) {
      throw new GoldenValidationError("A collection must contain at least one example.");
    }
    const records = [];
    for (const membership of [...collection.memberships].sort((left, right) =>
      left.exampleId.localeCompare(right.exampleId)
    )) {
      const example = await getExample(membership.exampleId);
      if (!example) {
        throw new GoldenValidationError(
          `Collection references missing example '${membership.exampleId}'.`
        );
      }
      for (const dimension of collection.dimensions) {
        const annotation = membership.annotations[dimension];
        if (
          !annotation ||
          !annotation.rationale.trim() ||
          !annotation.reviewerId.trim() ||
          !annotation.reviewedAt.trim()
        ) {
          throw new GoldenValidationError(
            `Example '${membership.exampleId}' needs a complete '${dimension}' annotation.`
          );
        }
        validateAnnotation(dimension, annotation);
      }
      records.push({
        exampleId: example.exampleId,
        contentFingerprint: example.contentFingerprint,
        content: example.content,
        sourceRefs: example.sourceRefs,
        tags: example.tags,
        annotations: membership.annotations,
        weight: membership.weight,
        notes: membership.notes,
      });
    }
    const manifest = {
      collectionId: collection.collectionId,
      collectionName: collection.name,
      version,
      dimensions: collection.dimensions,
      tags: collection.tags,
      records,
    };
    return {
      schemaVersion: 2,
      versionId: randomUUID(),
      ...manifest,
      manifestFingerprint: sha256(manifest),
      publisherId,
      publishedAt,
    };
  }

  async function publishCollection(
    collectionId: string,
    input: { version: string; expectedRevision: number; publisherId: string }
  ): Promise<GoldenDatasetVersion> {
    return withCollectionLock(collectionId, () =>
      publishCollectionUnlocked(collectionId, input)
    );
  }

  async function publishCollectionUnlocked(
    collectionId: string,
    input: { version: string; expectedRevision: number; publisherId: string }
  ): Promise<GoldenDatasetVersion> {
    const collection = await requireCollection(collectionId);
    const version = validateVersion(input.version);
    if (!input.publisherId.trim()) {
      throw new GoldenValidationError("publisherId is required.");
    }
    const snapshot = await buildSnapshot(collection, version, input.publisherId, now());
    const existing = await readJson<GoldenDatasetVersion>(versionPath(collectionId, version));
    if (existing) {
      if (existing.manifestFingerprint === snapshot.manifestFingerprint) {
        const metadataComplete =
          collection.latestPublishedVersion === version &&
          collection.latestPublishedAt === existing.publishedAt &&
          collection.lastPublishedFingerprint === existing.manifestFingerprint &&
          collection.status !== "draft";
        if (!metadataComplete) {
          assertRevision(collection, input.expectedRevision);
          await atomicWriteJson(collectionPath(collectionId), {
            ...collection,
            status: collection.status === "archived" ? "archived" : "published",
            latestPublishedVersion: version,
            latestPublishedAt: existing.publishedAt,
            lastPublishedFingerprint: existing.manifestFingerprint,
            revision: collection.revision + 1,
            updatedAt: existing.publishedAt,
          } satisfies GoldenCollection);
        }
        return existing;
      }
      throw new GoldenConflictError(
        `Version '${version}' already exists with different content.`
      );
    }
    assertRevision(collection, input.expectedRevision);
    if (
      collection.lastPublishedFingerprint === snapshot.manifestFingerprint &&
      collection.latestPublishedVersion !== version
    ) {
      throw new GoldenValidationError("The draft has no changes since its latest version.");
    }
    await atomicWriteJson(versionPath(collectionId, version), snapshot);
    const updated: GoldenCollection = {
      ...collection,
      status: collection.status === "archived" ? "archived" : "published",
      latestPublishedVersion: version,
      latestPublishedAt: snapshot.publishedAt,
      lastPublishedFingerprint: snapshot.manifestFingerprint,
      revision: collection.revision + 1,
      updatedAt: snapshot.publishedAt,
    };
    await atomicWriteJson(collectionPath(collectionId), updated);
    return snapshot;
  }

  async function listVersions(collectionId: string): Promise<GoldenDatasetVersion[]> {
    validateSafeSegment(collectionId, "collectionId");
    const versions = await readJsonDirectory<GoldenDatasetVersion>(
      path.join(versionsDirectory, collectionId)
    );
    return versions.sort((left, right) => right.publishedAt.localeCompare(left.publishedAt));
  }

  async function getVersion(
    collectionId: string,
    version: string
  ): Promise<GoldenDatasetVersion | null> {
    return readJson<GoldenDatasetVersion>(versionPath(collectionId, version));
  }

  async function exportCollectionVersion(
    collectionId: string,
    version: string,
    format: "jsonl" | "csv"
  ): Promise<GoldenExport> {
    const snapshot = await getVersion(collectionId, version);
    if (!snapshot) {
      throw new GoldenNotFoundError(
        `Version '${version}' of collection '${collectionId}' was not found.`
      );
    }
    return exportVersion(snapshot, format, false);
  }

  async function exportCollectionDraft(
    collectionId: string,
    format: "jsonl" | "csv"
  ): Promise<GoldenExport> {
    const collection = await requireCollection(collectionId);
    const snapshot = await buildSnapshot(collection, "draft-preview", "preview", now());
    return exportVersion(snapshot, format, true);
  }

  async function upgradeLegacyDataset(datasetId: string): Promise<GoldenCollection> {
    const safeId = validateSafeSegment(datasetId, "datasetId");
    const legacyPath = path.join(root, `${safeId}.json`);
    const legacy = await readJson<LegacyDatasetShape>(legacyPath);
    if (!legacy) throw new GoldenNotFoundError(`Legacy dataset '${safeId}' was not found.`);
    if ((legacy as { schemaVersion?: number }).schemaVersion) {
      throw new GoldenValidationError(`Dataset '${safeId}' is not a legacy artifact.`);
    }
    const resolved: GoldenExampleImport[] = [];
    for (const ref of legacy.recordRefs) {
      const record = await resolveLegacyRecord(ref);
      if (!record) {
        throw new GoldenValidationError(
          `Could not resolve legacy record ${ref.runId}/${ref.conversationId}/${ref.turnId}.`
        );
      }
      resolved.push(record);
    }
    const requestedDimensions = (legacy.filters.metricKeys ?? []).filter((key) =>
      metricKeySet.has(key)
    ) as GoldenMetricKey[];
    const inferredDimensions = resolved.flatMap((record) =>
      [...Object.keys(record.review.safetyScores), ...Object.keys(record.review.performanceScores)]
        .filter((key) => metricKeySet.has(key)) as GoldenMetricKey[]
    );
    const dimensions = validateDimensions(
      requestedDimensions.length > 0 ? requestedDimensions : inferredDimensions
    );
    const prepared = resolved.map((record) => {
      validateExampleImportInput(record);
      const annotations = Object.fromEntries(
        dimensions.flatMap((dimension) => {
          const annotation = annotationFromReview(dimension, record.review, record.source);
          return annotation ? [[dimension, annotation]] : [];
        })
      ) as Partial<Record<GoldenMetricKey, GoldenAnnotation>>;
      for (const dimension of dimensions) {
        const annotation = annotations[dimension];
        if (!annotation) {
          throw new GoldenValidationError(
            `Legacy record ${record.source.runId}/${record.source.conversationId}/${record.source.turnId} has no '${dimension}' human score.`
          );
        }
        validateAnnotation(dimension, annotation);
      }
      return { record, annotations };
    });
    if (legacy.status === "published" && prepared.length === 0) {
      throw new GoldenValidationError("A published legacy dataset must contain a record.");
    }
    const publishedVersion = normalizeLegacyVersion(legacy.version);
    if (legacy.status === "published") validateVersion(publishedVersion);
    return withFileLock(path.join(locksDirectory, "examples.lock"), async () => {
      await assertExampleImportsCompatible(prepared.map(({ record }) => record));
      let collection = await createCollection({
        name: legacy.name,
        description: `Upgraded from legacy golden dataset '${legacy.datasetId}'.`,
        dimensions,
        tags: [],
        legacyDatasetId: legacy.datasetId,
      });
      for (const { record, annotations } of prepared) {
        const example = await importExampleUnlocked(record);
        collection = await upsertMembership(collection.collectionId, {
          expectedRevision: collection.revision,
          exampleId: example.exampleId,
          annotations,
        });
      }
      if (legacy.status === "published") {
        await publishCollection(collection.collectionId, {
          version: publishedVersion,
          expectedRevision: collection.revision,
          publisherId: "legacy-upgrade",
        });
        collection = (await getCollection(collection.collectionId))!;
      }
      if (legacy.status === "archived") {
        collection = await updateCollection(collection.collectionId, {
          expectedRevision: collection.revision,
          status: "archived",
        });
      }
      return collection;
    });
  }

  return {
    importExample,
    listExamples,
    getExample,
    updateExampleMetadata,
    createCollection,
    listCollections,
    getCollection,
    updateCollection,
    upsertMembership,
    upsertMemberships,
    removeMembership,
    removeMemberships,
    publishCollection,
    listVersions,
    getVersion,
    exportCollectionVersion,
    exportCollectionDraft,
    upgradeLegacyDataset,
  };
}

export const goldenCatalog = createGoldenCatalog();
