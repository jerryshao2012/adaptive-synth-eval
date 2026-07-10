"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Plus, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useGoldenDatasets,
  useGoldenDataset,
  useCreateDataset,
  useRunList,
} from "@/hooks/use-evaluations";
import { DatasetList } from "@/components/golden/dataset-list";
import { CreateDatasetDialog } from "@/components/golden/create-dataset-dialog";
import { DatasetDetailPanel } from "@/components/golden/dataset-detail-panel";

export default function GoldenDatasetPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [viewDatasetId, setViewDatasetId] = useState<string | null>(null);

  const { data: datasets = [], isLoading, isError, refetch } = useGoldenDatasets();
  const { data: viewDataset, isLoading: viewLoading } =
    useGoldenDataset(viewDatasetId ?? undefined);
  const createDataset = useCreateDataset();
  const { data: runs = [] } = useRunList();

  const handleCreate = useCallback(
    async (name: string, version: string) => {
      try {
        await createDataset.mutateAsync({
          name,
          version,
          filters: {
            runIds: runs.map((r) => r.runId),
          },
        });
        queryClient.invalidateQueries({ queryKey: ["golden-datasets"] });
      } catch {
        // handled by mutation
      }
    },
    [createDataset, runs, queryClient]
  );

  const handleExport = useCallback(
    (datasetId: string, format: "jsonl" | "csv") => {
      const url = `/api/golden-dataset/${datasetId}/export?format=${format}`;
      window.open(url, "_blank");
    },
    []
  );

  const handleArchive = useCallback(
    async (datasetId: string) => {
      try {
        const res = await fetch(`/api/golden-dataset/${datasetId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "archived" }),
        });
        if (res.ok) {
          queryClient.invalidateQueries({ queryKey: ["golden-datasets"] });
        }
      } catch {
        // handled silently
      }
    },
    [queryClient]
  );

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["golden-datasets"] });
  }

  return (
    <div className="px-4 py-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-base font-semibold text-foreground">
            Golden Dataset
          </h1>
          <p className="text-xs text-muted-foreground">
            Curate reviewed evaluation records for model benchmarking and
            fine-tuning.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isLoading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1.5 ${isLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            New Dataset
          </Button>
        </div>
      </div>

      {/* Error */}
      {isError && (
        <div className="text-sm text-destructive mb-4">
          Failed to load datasets.
          <Button variant="link" size="sm" onClick={() => refetch()} className="ml-2">
            Retry
          </Button>
        </div>
      )}

      {/* Dataset list */}
      {!isError && (
        <DatasetList
          datasets={datasets}
          isLoading={isLoading}
          onView={(id) => setViewDatasetId(id)}
          onExport={handleExport}
          onArchive={handleArchive}
        />
      )}

      {/* Create Dialog */}
      <CreateDatasetDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreate={handleCreate}
        isPending={createDataset.isPending}
      />

      {/* Detail Panel */}
      <DatasetDetailPanel
        open={Boolean(viewDatasetId)}
        dataset={viewDataset ?? null}
        isLoading={viewLoading}
        onClose={() => setViewDatasetId(null)}
        onExport={handleExport}
      />
    </div>
  );
}
