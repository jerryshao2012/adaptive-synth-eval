"use client";

import { useState } from "react";
import { Download, Plus, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  GoldenAnnotation,
  GoldenCollection,
  GoldenDatasetVersion,
  GoldenExample,
  GoldenMembership,
  GoldenMetricKey,
} from "@/types/evaluation";

type CollectionDetail = GoldenCollection & { versions: GoldenDatasetVersion[] };

interface Props {
  open: boolean;
  collection?: CollectionDetail;
  examples: GoldenExample[];
  isLoading: boolean;
  isPending: boolean;
  onClose: () => void;
  onAddExamples: (ids: string[]) => Promise<void>;
  onSaveMembership: (
    exampleId: string,
    annotations: GoldenMembership["annotations"],
    weight: number,
    notes: string
  ) => Promise<void>;
  onRemoveMembership: (exampleId: string) => Promise<void>;
  onRemoveExamples: (ids: string[]) => Promise<void>;
  onPublish: (version: string) => Promise<void>;
}

function sourceAnnotation(
  example: GoldenExample,
  metric: GoldenMetricKey
): GoldenAnnotation | undefined {
  const score =
    example.reviewSnapshot.safetyScores[metric] ??
    example.reviewSnapshot.performanceScores[metric];
  if (!score) return undefined;
  const source = example.sourceRefs[0];
  return {
    expectedStatus: score.status,
    expectedScore: score.humanScore,
    rationale:
      example.reviewSnapshot.notes.trim() || "Imported from an approved human review.",
    reviewerId: source?.reviewerId ?? "dashboard-curator",
    reviewedAt: source?.reviewedAt ?? new Date().toISOString(),
  };
}

export function defaultMembershipAnnotations(
  example: GoldenExample,
  dimensions: GoldenMetricKey[]
): GoldenMembership["annotations"] {
  return Object.fromEntries(
    dimensions.flatMap((metric) => {
      const annotation = sourceAnnotation(example, metric);
      return annotation ? [[metric, annotation]] : [];
    })
  );
}

function MembershipEditor({
  membership,
  example,
  dimensions,
  disabled,
  onSave,
  onRemove,
}: {
  membership: GoldenMembership;
  example?: GoldenExample;
  dimensions: GoldenMetricKey[];
  disabled: boolean;
  onSave: Props["onSaveMembership"];
  onRemove: Props["onRemoveMembership"];
}) {
  const [annotations, setAnnotations] = useState(membership.annotations);
  const [weight, setWeight] = useState(membership.weight);
  const [notes, setNotes] = useState(membership.notes);
  function updateAnnotation(metric: GoldenMetricKey, patch: Partial<GoldenAnnotation>) {
    const fallback =
      (example ? sourceAnnotation(example, metric) : undefined) ?? {
          expectedStatus: "pass" as const,
          rationale: "",
          reviewerId: "dashboard-curator",
          reviewedAt: new Date().toISOString(),
        };
    setAnnotations((current) => ({
      ...current,
      [metric]: { ...(current[metric] ?? fallback), ...patch },
    }));
  }

  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">
            {example?.content.userText ?? membership.exampleId}
          </p>
          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
            {example?.content.responseText ?? "Canonical example unavailable"}
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={() => onRemove(membership.exampleId)} disabled={disabled} aria-label={`Remove ${membership.exampleId}`}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-3 space-y-3">
        {dimensions.map((metric) => {
          const annotation = annotations[metric] ?? (example ? sourceAnnotation(example, metric) : undefined);
          return (
            <div key={metric} className="grid gap-2 rounded-md bg-muted/40 p-3 md:grid-cols-[9rem_7rem_1fr]">
              <label className="text-xs font-medium capitalize">{metric.replaceAll("_", " ")}
                <select value={annotation?.expectedStatus ?? "pass"} onChange={(event) => updateAnnotation(metric, { expectedStatus: event.target.value as GoldenAnnotation["expectedStatus"] })} className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-xs">
                  <option value="pass">pass</option><option value="warn">warn</option><option value="fail">fail</option>
                </select>
              </label>
              <label className="text-xs font-medium">Score
                <input type="number" min={0} max={100} value={annotation?.expectedScore ?? ""} onChange={(event) => updateAnnotation(metric, { expectedScore: event.target.value ? Number(event.target.value) : undefined })} className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-xs" />
              </label>
              <label className="text-xs font-medium">Rationale
                <textarea value={annotation?.rationale ?? ""} onChange={(event) => updateAnnotation(metric, { rationale: event.target.value })} className="mt-1 min-h-16 w-full rounded-md border bg-background p-2 text-xs" />
              </label>
            </div>
          );
        })}
        <div className="grid gap-2 md:grid-cols-[8rem_1fr_auto]">
          <label className="text-xs font-medium">Weight<input type="number" min={0.01} step={0.25} value={weight} onChange={(event) => setWeight(Number(event.target.value))} className="mt-1 h-8 w-full rounded-md border bg-background px-2" /></label>
          <label className="text-xs font-medium">Membership notes<input value={notes} onChange={(event) => setNotes(event.target.value)} className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-xs" /></label>
          <Button size="sm" className="self-end" disabled={disabled} onClick={() => onSave(membership.exampleId, annotations, weight, notes)}><Save className="mr-1 h-4 w-4" />Save</Button>
        </div>
      </div>
    </div>
  );
}

export function CollectionWorkspace({ open, collection, examples, isLoading, isPending, onClose, onAddExamples, onSaveMembership, onRemoveMembership, onRemoveExamples, onPublish }: Props) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([]);
  const [version, setVersion] = useState(() => {
    if (!collection?.latestPublishedVersion) return "1.0.0";
    const [major, minor] = collection.latestPublishedVersion.split(".").map(Number);
    return `${major}.${minor + 1}.0`;
  });
  const members = new Set(collection?.memberships.map((member) => member.exampleId) ?? []);
  const available = examples.filter((example) => !members.has(example.exampleId));

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{collection?.name ?? "Collection"} workspace</DialogTitle>
          <DialogDescription>Curate metric-specific annotations, publish immutable versions, and export reproducible snapshots.</DialogDescription>
        </DialogHeader>
        {isLoading || !collection ? <p className="py-8 text-center text-sm text-muted-foreground">Loading collection…</p> : (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-1.5">{collection.dimensions.map((metric) => <Badge key={metric}>{metric.replaceAll("_", " ")}</Badge>)}<Badge variant="outline">revision {collection.revision}</Badge></div>
            <section className="rounded-lg border p-3">
              <h3 className="text-sm font-semibold">Add canonical examples</h3>
              <div className="mt-2 max-h-36 space-y-1 overflow-y-auto">
                {available.length === 0 ? <p className="text-xs text-muted-foreground">All available examples are already included.</p> : available.map((example) => (
                  <label key={example.exampleId} className="flex items-center gap-2 rounded p-2 text-xs hover:bg-muted/50"><input type="checkbox" checked={selectedIds.includes(example.exampleId)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, example.exampleId] : current.filter((id) => id !== example.exampleId))} /><span className="line-clamp-1">{example.content.userText}</span></label>
                ))}
              </div>
              <Button size="sm" className="mt-2" disabled={!selectedIds.length || isPending} onClick={async () => { await onAddExamples(selectedIds); setSelectedIds([]); }}><Plus className="mr-1 h-4 w-4" />Add selected examples</Button>
            </section>
            <section className="space-y-2"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">Membership annotations</h3><Button variant="outline" size="sm" disabled={!selectedMemberIds.length || isPending} onClick={async () => { await onRemoveExamples(selectedMemberIds); setSelectedMemberIds([]); }}><Trash2 className="mr-1 h-4 w-4" />Remove selected</Button></div>{collection.memberships.length === 0 ? <p className="text-xs text-muted-foreground">Add an example to begin annotation.</p> : collection.memberships.map((membership) => <div key={membership.exampleId} className="flex items-start gap-2"><input aria-label={`Select ${membership.exampleId}`} type="checkbox" className="mt-4" checked={selectedMemberIds.includes(membership.exampleId)} onChange={(event) => setSelectedMemberIds((current) => event.target.checked ? [...current, membership.exampleId] : current.filter((id) => id !== membership.exampleId))} /><div className="min-w-0 flex-1"><MembershipEditor key={membership.updatedAt} membership={membership} example={examples.find((item) => item.exampleId === membership.exampleId)} dimensions={collection.dimensions} disabled={isPending} onSave={onSaveMembership} onRemove={onRemoveMembership} /></div></div>)}</section>
            <section className="grid gap-4 rounded-lg border p-3 lg:grid-cols-2">
              <div><h3 className="text-sm font-semibold">Publish immutable snapshot</h3><div className="mt-2 flex flex-wrap items-end gap-2"><label className="text-xs font-medium">Publish version<input aria-label="Publish version" value={version} onChange={(event) => setVersion(event.target.value)} className="mt-1 h-9 w-32 rounded-md border bg-background px-3 font-mono text-sm" /></label><Button disabled={isPending || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version)} onClick={() => onPublish(version)}>Publish version</Button><Button variant="outline" onClick={() => window.open(`/api/golden-dataset/collections/${collection.collectionId}/draft/export?format=jsonl`, "_blank")}><Download className="mr-1 h-4 w-4" />Draft JSONL</Button><Button variant="outline" onClick={() => window.open(`/api/golden-dataset/collections/${collection.collectionId}/draft/export?format=csv`, "_blank")}><Download className="mr-1 h-4 w-4" />Draft CSV</Button></div><p className="mt-2 text-xs text-amber-600">Draft preview exports are mutable and not suitable for reproducible evaluation.</p></div>
              <div><h3 className="text-sm font-semibold">Published versions</h3>{collection.versions.length === 0 ? <p className="mt-2 text-xs text-muted-foreground">No published versions.</p> : <div className="mt-2 space-y-2">{collection.versions.map((item) => <div key={item.versionId} className="flex items-center justify-between rounded-md bg-muted/40 p-2 text-xs"><span><span className="font-mono">v{item.version}</span> · {item.records.length} examples</span><div><Button variant="ghost" size="sm" onClick={() => window.open(`/api/golden-dataset/collections/${collection.collectionId}/versions/${item.version}/export?format=jsonl`, "_blank")}>JSONL</Button><Button variant="ghost" size="sm" onClick={() => window.open(`/api/golden-dataset/collections/${collection.collectionId}/versions/${item.version}/export?format=csv`, "_blank")}>CSV</Button></div></div>)}</div>}</div>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
