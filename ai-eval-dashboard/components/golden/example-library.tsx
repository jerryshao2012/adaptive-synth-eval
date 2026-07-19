"use client";

import { useMemo, useState } from "react";
import { Database, Eye, RefreshCw, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GOLDEN_METRIC_KEYS } from "@/lib/golden-metrics";
import type { GoldenCollection, GoldenExample, GoldenMetricKey } from "@/types/evaluation";

interface ExampleLibraryProps {
  examples: GoldenExample[];
  collections: GoldenCollection[];
  isLoading: boolean;
  search: string;
  dimension?: GoldenMetricKey;
  tag: string;
  runId: string;
  collectionId: string;
  onSearchChange: (value: string) => void;
  onDimensionChange: (value?: GoldenMetricKey) => void;
  onTagChange: (value: string) => void;
  onRunIdChange: (value: string) => void;
  onCollectionIdChange: (value: string) => void;
  onSync: () => void;
  isSyncing: boolean;
}

export function ExampleLibrary({
  examples,
  collections,
  isLoading,
  search,
  dimension,
  tag,
  runId,
  collectionId,
  onSearchChange,
  onDimensionChange,
  onTagChange,
  onRunIdChange,
  onCollectionIdChange,
  onSync,
  isSyncing,
}: ExampleLibraryProps) {
  const [selected, setSelected] = useState<GoldenExample | null>(null);
  const usage = useMemo(() => {
    const counts = new Map<string, number>();
    for (const collection of collections) {
      for (const membership of collection.memberships) {
        counts.set(membership.exampleId, (counts.get(membership.exampleId) ?? 0) + 1);
      }
    }
    return counts;
  }, [collections]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3">
        <label className="relative min-w-56 flex-1">
          <span className="sr-only">Search examples</span>
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            aria-label="Search examples"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search prompt, response, tag, or run"
            className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-3 text-sm"
          />
        </label>
        <select
          aria-label="Filter example dimension"
          value={dimension ?? ""}
          onChange={(event) =>
            onDimensionChange((event.target.value || undefined) as GoldenMetricKey | undefined)
          }
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">All dimensions</option>
          {GOLDEN_METRIC_KEYS.map((metric) => (
            <option key={metric} value={metric}>{metric.replaceAll("_", " ")}</option>
          ))}
        </select>
        <input
          aria-label="Filter example tag"
          value={tag}
          onChange={(event) => onTagChange(event.target.value)}
          placeholder="Tag"
          className="h-9 w-32 rounded-md border border-input bg-background px-3 text-sm"
        />
        <select
          aria-label="Filter collection usage"
          value={collectionId}
          onChange={(event) => onCollectionIdChange(event.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">Any collection</option>
          {collections.map((collection) => (
            <option key={collection.collectionId} value={collection.collectionId}>
              {collection.name}
            </option>
          ))}
        </select>
        <input
          aria-label="Filter source run"
          value={runId}
          onChange={(event) => onRunIdChange(event.target.value)}
          placeholder="Source run"
          className="h-9 w-36 rounded-md border border-input bg-background px-3 text-sm"
        />
        <Button variant="outline" size="sm" onClick={onSync} disabled={isSyncing}>
          <RefreshCw className={`mr-1.5 h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} />
          Sync approved reviews
        </Button>
      </div>

      {!isLoading && examples.length === 0 ? (
        <div className="flex flex-col items-center py-16 text-center">
          <Database className="mb-3 h-8 w-8 text-muted-foreground" />
          <p className="font-medium">No canonical examples found</p>
          <p className="text-sm text-muted-foreground">Sync approved reviews or adjust the filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {examples.map((example) => {
            const count = usage.get(example.exampleId) ?? 0;
            return (
              <Card key={example.exampleId} className="border-border bg-card">
                <CardContent className="space-y-3 p-4">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Prompt</p>
                    <p className="mt-1 line-clamp-2 text-sm font-medium">{example.content.userText}</p>
                  </div>
                  <p className="line-clamp-2 text-sm text-muted-foreground">{example.content.responseText}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {example.tags.map((item) => <Badge key={item} variant="outline">{item}</Badge>)}
                    <Badge variant="secondary">
                      Used in {count} {count === 1 ? "collection" : "collections"}
                    </Badge>
                    {(example.similarExampleIds?.length ?? 0) > 0 && (
                      <Badge variant="outline">Possible duplicate</Badge>
                    )}
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{example.sourceRefs.map((source) => source.runId).join(", ")}</span>
                    <Button variant="ghost" size="sm" onClick={() => setSelected(example)}>
                      <Eye className="mr-1 h-4 w-4" />Details
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Canonical example</DialogTitle>
            <DialogDescription>{selected?.contentFingerprint}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              <section><h3 className="text-xs font-semibold uppercase text-muted-foreground">Prompt</h3><p className="mt-1 text-sm">{selected.content.userText}</p></section>
              <section><h3 className="text-xs font-semibold uppercase text-muted-foreground">Response</h3><p className="mt-1 text-sm">{selected.content.responseText}</p></section>
              <section>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">Provenance</h3>
                {selected.sourceRefs.map((source) => (
                  <p key={`${source.runId}-${source.turnId}`} className="mt-1 font-mono text-xs">
                    {source.runId} / {source.conversationId} / {source.turnId}
                  </p>
                ))}
              </section>
              <section>
                <h3 className="text-xs font-semibold uppercase text-muted-foreground">Collection annotations</h3>
                {collections.flatMap((collection) =>
                  collection.memberships
                    .filter((member) => member.exampleId === selected.exampleId)
                    .map((member) => (
                      <div key={collection.collectionId} className="mt-2 rounded-md border p-3">
                        <p className="text-sm font-medium">{collection.name}</p>
                        {Object.entries(member.annotations).map(([metric, annotation]) => annotation && (
                          <p key={metric} className="mt-1 text-xs text-muted-foreground">
                            {metric}: {annotation.expectedStatus} — {annotation.rationale}
                          </p>
                        ))}
                      </div>
                    ))
                )}
              </section>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
