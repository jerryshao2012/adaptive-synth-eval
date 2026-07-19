"use client";

import { useState } from "react";
import { Database, FolderKanban, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CollectionListV2 } from "@/components/golden/collection-list-v2";
import {
  CollectionWorkspace,
  defaultMembershipAnnotations,
} from "@/components/golden/collection-workspace";
import { CreateCollectionDialog } from "@/components/golden/create-collection-dialog";
import { ExampleLibrary } from "@/components/golden/example-library";
import {
  useCreateGoldenCollection,
  useGoldenCollections,
  useGoldenCollectionV2,
  useGoldenExamplesV2,
  usePublishGoldenCollection,
  useRemoveGoldenMembership,
  useRemoveGoldenMemberships,
  useRunList,
  useSyncApprovedGoldenExamples,
  useUpdateGoldenCollection,
  useUpsertGoldenMembership,
  useUpsertGoldenMemberships,
} from "@/hooks/use-evaluations";
import type { GoldenCollection, GoldenMetricKey } from "@/types/evaluation";
import { GOLDEN_METRIC_KEYS } from "@/lib/golden-metrics";

type WorkspaceView = "examples" | "collections";

export default function GoldenDatasetPage() {
  const [view, setView] = useState<WorkspaceView>("examples");
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedCollectionId, setSelectedCollectionId] = useState<string>();
  const [message, setMessage] = useState<string>();
  const [exampleSearch, setExampleSearch] = useState("");
  const [exampleDimension, setExampleDimension] = useState<GoldenMetricKey>();
  const [exampleTag, setExampleTag] = useState("");
  const [exampleRun, setExampleRun] = useState("");
  const [exampleCollectionId, setExampleCollectionId] = useState("");
  const [collectionSearch, setCollectionSearch] = useState("");
  const [collectionStatus, setCollectionStatus] = useState<GoldenCollection["status"] | "">("");
  const [collectionDimension, setCollectionDimension] = useState<GoldenMetricKey>();
  const [collectionTag, setCollectionTag] = useState("");

  const examplesQuery = useGoldenExamplesV2({
    search: exampleSearch || undefined,
    dimensions: exampleDimension ? [exampleDimension] : undefined,
    tags: exampleTag ? [exampleTag] : undefined,
    runId: exampleRun || undefined,
    collectionId: exampleCollectionId || undefined,
  });
  const catalogExamplesQuery = useGoldenExamplesV2();
  const collectionsQuery = useGoldenCollections({
    search: collectionSearch || undefined,
    status: collectionStatus || undefined,
    dimensions: collectionDimension ? [collectionDimension] : undefined,
    tags: collectionTag ? [collectionTag] : undefined,
  });
  const catalogCollectionsQuery = useGoldenCollections();
  const collectionQuery = useGoldenCollectionV2(selectedCollectionId);
  const { data: runs = [] } = useRunList();
  const createCollection = useCreateGoldenCollection();
  const updateCollection = useUpdateGoldenCollection();
  const upsertMembership = useUpsertGoldenMembership();
  const upsertMemberships = useUpsertGoldenMemberships();
  const removeMembership = useRemoveGoldenMembership();
  const removeMemberships = useRemoveGoldenMemberships();
  const publishCollection = usePublishGoldenCollection();
  const syncApproved = useSyncApprovedGoldenExamples();

  const examples = examplesQuery.data ?? [];
  const catalogExamples = catalogExamplesQuery.data ?? [];
  const collections = collectionsQuery.data ?? [];
  const catalogCollections = catalogCollectionsQuery.data ?? [];
  const visibleCollections = collectionStatus
    ? collections
    : collections.filter((collection) => collection.status !== "archived");
  const selectedCollection = collectionQuery.data;
  const isMutating =
    updateCollection.isPending ||
    upsertMembership.isPending ||
    upsertMemberships.isPending ||
    removeMembership.isPending ||
    removeMemberships.isPending ||
    publishCollection.isPending;

  async function showResult(action: () => Promise<unknown>, success: string) {
    setMessage(undefined);
    try {
      await action();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Golden dataset operation failed.");
      throw error;
    }
  }

  async function addExamples(ids: string[]) {
    if (!selectedCollection) return;
    const members = ids.flatMap((id) => {
      const example = catalogExamples.find((item) => item.exampleId === id);
      return example
        ? [{ exampleId: id, annotations: defaultMembershipAnnotations(example, selectedCollection.dimensions) }]
        : [];
    });
    await upsertMemberships.mutateAsync({
      collectionId: selectedCollection.collectionId,
      expectedRevision: selectedCollection.revision,
      members,
    });
    setMessage(`${ids.length} ${ids.length === 1 ? "example" : "examples"} added.`);
  }

  return (
    <div className="space-y-4 px-4 py-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold">Golden datasets</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Reuse approved examples across metric-specific collections and publish immutable versions.
          </p>
        </div>
        {view === "collections" && (
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1.5 h-4 w-4" />New collection
          </Button>
        )}
      </header>

      <nav className="flex w-fit gap-1 rounded-lg bg-muted p-1" aria-label="Golden dataset workspace">
        <Button variant={view === "examples" ? "default" : "ghost"} size="sm" onClick={() => setView("examples")}>
          <Database className="mr-1.5 h-4 w-4" />Example Library
        </Button>
        <Button variant={view === "collections" ? "default" : "ghost"} size="sm" onClick={() => setView("collections")}>
          <FolderKanban className="mr-1.5 h-4 w-4" />Collections
        </Button>
      </nav>

      {message && <div role="status" className="rounded-md border border-border bg-card px-3 py-2 text-xs">{message}</div>}
      {(examplesQuery.isError || collectionsQuery.isError) && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Failed to load the golden dataset catalog.
        </div>
      )}

      {view === "examples" ? (
        <ExampleLibrary
          examples={examples}
          collections={catalogCollections}
          isLoading={examplesQuery.isLoading}
          search={exampleSearch}
          dimension={exampleDimension}
          tag={exampleTag}
          runId={exampleRun}
          collectionId={exampleCollectionId}
          onSearchChange={setExampleSearch}
          onDimensionChange={setExampleDimension}
          onTagChange={setExampleTag}
          onRunIdChange={setExampleRun}
          onCollectionIdChange={setExampleCollectionId}
          onSync={() =>
            void showResult(
              () => syncApproved.mutateAsync({ runIds: runs.map((run) => run.runId) }),
              "Approved reviews synchronized."
            ).catch(() => undefined)
          }
          isSyncing={syncApproved.isPending}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 rounded-lg border bg-card p-3">
            <input aria-label="Search collections" value={collectionSearch} onChange={(event) => setCollectionSearch(event.target.value)} placeholder="Search collections" className="h-9 min-w-56 flex-1 rounded-md border bg-background px-3 text-sm" />
            <select aria-label="Filter collection status" value={collectionStatus} onChange={(event) => setCollectionStatus(event.target.value as GoldenCollection["status"] | "")} className="h-9 rounded-md border bg-background px-2 text-sm"><option value="">All statuses</option><option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option></select>
            <select aria-label="Filter collection dimension" value={collectionDimension ?? ""} onChange={(event) => setCollectionDimension((event.target.value || undefined) as GoldenMetricKey | undefined)} className="h-9 rounded-md border bg-background px-2 text-sm"><option value="">All dimensions</option>{GOLDEN_METRIC_KEYS.map((metric) => <option key={metric} value={metric}>{metric.replaceAll("_", " ")}</option>)}</select>
            <input aria-label="Filter collection tag" value={collectionTag} onChange={(event) => setCollectionTag(event.target.value)} placeholder="Tag" className="h-9 w-32 rounded-md border bg-background px-3 text-sm" />
          </div>
          <CollectionListV2
            collections={visibleCollections}
            allCollections={catalogCollections}
            isLoading={collectionsQuery.isLoading}
            onManage={setSelectedCollectionId}
            onArchive={(collection) =>
              void showResult(
                () => updateCollection.mutateAsync({ collectionId: collection.collectionId, expectedRevision: collection.revision, status: "archived" }),
                `${collection.name} archived.`
              ).catch(() => undefined)
            }
          />
        </div>
      )}

      <CreateCollectionDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        isPending={createCollection.isPending}
        onCreate={async (input) => {
          await showResult(() => createCollection.mutateAsync(input), `${input.name} created.`);
        }}
      />

      <CollectionWorkspace
        key={`${selectedCollectionId ?? "closed"}-${selectedCollection?.latestPublishedVersion ?? "draft"}`}
        open={Boolean(selectedCollectionId)}
        collection={selectedCollection}
        examples={catalogExamples}
        isLoading={collectionQuery.isLoading}
        isPending={isMutating}
        onClose={() => setSelectedCollectionId(undefined)}
        onAddExamples={addExamples}
        onSaveMembership={async (exampleId, annotations, weight, notes) => {
          if (!selectedCollection) return;
          await showResult(
            () => upsertMembership.mutateAsync({ collectionId: selectedCollection.collectionId, expectedRevision: selectedCollection.revision, exampleId, annotations, weight, notes }),
            "Membership annotation saved."
          );
        }}
        onRemoveMembership={async (exampleId) => {
          if (!selectedCollection) return;
          await showResult(
            () => removeMembership.mutateAsync({ collectionId: selectedCollection.collectionId, exampleId, expectedRevision: selectedCollection.revision }),
            "Example removed from collection."
          );
        }}
        onRemoveExamples={async (exampleIds) => {
          if (!selectedCollection) return;
          await showResult(
            () => removeMemberships.mutateAsync({ collectionId: selectedCollection.collectionId, exampleIds, expectedRevision: selectedCollection.revision }),
            `${exampleIds.length} ${exampleIds.length === 1 ? "example" : "examples"} removed.`
          );
        }}
        onPublish={async (version) => {
          if (!selectedCollection) return;
          await showResult(
            () => publishCollection.mutateAsync({ collectionId: selectedCollection.collectionId, version, expectedRevision: selectedCollection.revision, publisherId: "dashboard-curator" }),
            `Version ${version} published.`
          );
        }}
      />
    </div>
  );
}
