"use client";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { X, FileJson, FileSpreadsheet } from "lucide-react";
import { format, parseISO } from "date-fns";
import type { GoldenDataset } from "@/types/evaluation";

interface DatasetDetailPanelProps {
  open: boolean;
  dataset: GoldenDataset | null;
  isLoading: boolean;
  onClose: () => void;
  onExport: (datasetId: string, format: "jsonl" | "csv") => void;
}

export function DatasetDetailPanel({
  open,
  dataset,
  isLoading,
  onClose,
  onExport,
}: DatasetDetailPanelProps) {
  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close dataset panel"
          className="fixed inset-0 z-40 bg-black/35 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed top-14 right-0 bottom-0 z-50 w-full max-w-[520px] border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        <div className="flex h-14 items-center justify-between border-b border-border px-4 shrink-0">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">
              {dataset?.name ?? "Dataset Details"}
            </div>
            {dataset && (
              <div className="text-xs text-muted-foreground">
                v{dataset.version} · {dataset.stats.totalRecords} records
              </div>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onClose}
            aria-label="Close dataset panel"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <ScrollArea className="h-[calc(100%-3.5rem)] p-4">
          {isLoading && (
            <div className="text-sm text-muted-foreground p-4">
              Loading dataset...
            </div>
          )}

          {!isLoading && !dataset && (
            <div className="text-sm text-muted-foreground p-4">
              Select a dataset to view details.
            </div>
          )}

          {!isLoading && dataset && (
            <div className="space-y-4">
              {/* Stats */}
              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Statistics
                </h3>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-muted-foreground">Total Records</span>
                    <p className="text-foreground font-medium tabular-nums">
                      {dataset.stats.totalRecords}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Reviewed</span>
                    <p className="text-foreground font-medium tabular-nums">
                      {dataset.stats.reviewedCount}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Agreement</span>
                    <p className="text-foreground font-medium tabular-nums">
                      {dataset.stats.interRaterAgreement}%
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Status</span>
                    <Badge variant="outline" className="text-[10px] mt-0.5">
                      {dataset.status}
                    </Badge>
                  </div>
                </div>
              </section>

              {/* Record Refs */}
              <section className="rounded-md border border-border bg-background p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Record References
                </h3>
                {dataset.recordRefs.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No records in this dataset yet.
                  </p>
                ) : (
                  <div className="space-y-1 max-h-[320px] overflow-y-auto">
                    {dataset.recordRefs.slice(0, 100).map((ref, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-muted-foreground font-mono py-1"
                      >
                        <span className="text-foreground">{ref.turnId}</span>
                        <span>·</span>
                        <span className="truncate">{ref.runId}</span>
                      </div>
                    ))}
                    {dataset.recordRefs.length > 100 && (
                      <p className="text-xs text-muted-foreground pt-2">
                        ... and {dataset.recordRefs.length - 100} more records
                      </p>
                    )}
                  </div>
                )}
              </section>

              {/* Metadata */}
              <section className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
                <div>
                  Created:{" "}
                  {format(parseISO(dataset.createdAt), "PPpp")}
                </div>
                <div>
                  Updated:{" "}
                  {format(parseISO(dataset.updatedAt), "PPpp")}
                </div>
                {dataset.filters.runIds &&
                  dataset.filters.runIds.length > 0 && (
                    <div className="mt-1">
                      Source runs: {dataset.filters.runIds.join(", ")}
                    </div>
                  )}
              </section>

              {/* Export actions */}
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={() => onExport(dataset.datasetId, "jsonl")}
                  className="h-8 text-xs"
                >
                  <FileJson className="h-3.5 w-3.5 mr-1.5" />
                  Export JSONL
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onExport(dataset.datasetId, "csv")}
                  className="h-8 text-xs"
                >
                  <FileSpreadsheet className="h-3.5 w-3.5 mr-1.5" />
                  Export CSV
                </Button>
              </div>
            </div>
          )}
        </ScrollArea>
      </aside>
    </>
  );
}
