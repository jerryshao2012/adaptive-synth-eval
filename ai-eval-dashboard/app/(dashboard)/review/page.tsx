"use client";

import { useMemo, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useReviewQueue,
  useReviewStats,
  useBulkReviewAction,
  useRunList,
  useReviewDetail,
  useSaveReview,
} from "@/hooks/use-evaluations";
import { ReviewStatsBar } from "@/components/review/review-stats-bar";
import { AgreementChart } from "@/components/review/agreement-chart";
import { ReviewFilters } from "@/components/review/review-filters";
import { ReviewTable } from "@/components/review/review-table";
import { BulkActionsBar } from "@/components/review/bulk-actions-bar";
import { ReviewDetailPanel } from "@/components/review/review-detail-panel";
import { EmptyState, ErrorCard } from "@/components/shared/empty-state";
import type {
  ReviewQueueFilters,
  ReviewQueueItem,
  HumanReview,
} from "@/types/evaluation";

const DEFAULT_FILTERS: ReviewQueueFilters = {
  page: 1,
  pageSize: 50,
  sortBy: "timestamp",
  sortOrder: "desc",
};

function itemKey(item: ReviewQueueItem): string {
  return `${item.runId}:${item.turnId}`;
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<ReviewQueueFilters>(DEFAULT_FILTERS);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeItemKey, setActiveItemKey] = useState<string | null>(null);

  const { data: runs = [], isLoading: runsLoading } = useRunList();
  const {
    data: queueData,
    isLoading: queueLoading,
    isError: queueError,
    error: queueErrorObj,
  } = useReviewQueue(filters as Record<string, unknown>);
  const { data: stats, isLoading: statsLoading } = useReviewStats();
  const bulkAction = useBulkReviewAction();
  const saveReview = useSaveReview();

  // Detail panel state
  const [detailRunId, setDetailRunId] = useState<string>("");
  const [detailTurnId, setDetailTurnId] = useState<string>("");
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  const {
    data: detailData,
    isLoading: detailLoading,
  } = useReviewDetail(
    isPanelOpen ? detailRunId : undefined,
    isPanelOpen ? detailTurnId : undefined
  );

  const activeItem = useMemo(() => {
    if (!activeItemKey || !queueData?.items) return null;
    return queueData.items.find((item) => itemKey(item) === activeItemKey) ?? null;
  }, [activeItemKey, queueData]);

  const handleSort = useCallback(
    (column: NonNullable<ReviewQueueFilters["sortBy"]>) => {
      setFilters((prev) => ({
        ...prev,
        sortBy: column,
        sortOrder:
          prev.sortBy === column && prev.sortOrder === "asc" ? "desc" : "asc",
        page: 1,
      }));
    },
    []
  );

  async function handleApproveAll() {
    const records = Array.from(selectedIds).map((key) => {
      const [runId, turnId] = key.split(":");
      return { runId, turnId };
    });
    try {
      await bulkAction.mutateAsync({ action: "approve", records });
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
    } catch {
      // error handled by mutation state
    }
  }

  async function handleFlagAll() {
    const records = Array.from(selectedIds).map((key) => {
      const [runId, turnId] = key.split(":");
      return { runId, turnId };
    });
    try {
      await bulkAction.mutateAsync({
        action: "flag",
        records,
        flag: "needs_discussion",
      });
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
    } catch {
      // error handled by mutation state
    }
  }

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    queryClient.invalidateQueries({ queryKey: ["review-stats"] });
  }

  const totalPages = queueData
    ? Math.max(1, Math.ceil(queueData.total / queueData.pageSize))
    : 1;

  return (
    <div className="px-4 py-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-base font-semibold text-foreground">
            Review Queue
          </h1>
          <p className="text-xs text-muted-foreground">
            Review and correct AI evaluation scores to build a golden dataset.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={queueLoading}
        >
          <RefreshCw
            className={`h-4 w-4 mr-1.5 ${queueLoading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {/* Stats bar */}
      {statsLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-card px-4 py-3"
            >
              <Skeleton className="h-4 w-16 mb-2" />
              <Skeleton className="h-6 w-12" />
            </div>
          ))}
        </div>
      ) : (
        <ReviewStatsBar stats={stats} isLoading={false} />
      )}

      {/* Inter-Rater Agreement Chart */}
      <AgreementChart stats={stats} isLoading={statsLoading} />

      {/* Filters */}
      <ReviewFilters
        filters={filters}
        onChange={(next) =>
          setFilters({ ...next, page: next.page ?? 1 })
        }
        runs={runs}
      />

      {/* Error state */}
      {queueError && (
        <ErrorCard
          message={
            (queueErrorObj as Error)?.message || "Failed to load review queue."
          }
        />
      )}

      {/* Empty state */}
      {!queueLoading && !queueError && queueData?.items.length === 0 && (
        <EmptyState
          message="No evaluation records found."
          suggestion="Generate an evaluation run from the Monitor page, then return here to review scores."
        />
      )}

      {/* Table */}
      {(!queueError && (queueLoading || (queueData && queueData.items.length > 0))) && (
        <>
          {queueLoading ? (
            <div className="rounded-lg border border-border bg-card p-6 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : queueData ? (
            <ReviewTable
              items={queueData.items}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              onRowClick={(item) => {
                setActiveItemKey(itemKey(item));
                setDetailRunId(item.runId);
                setDetailTurnId(item.turnId);
                setIsPanelOpen(true);
              }}
              activeItemKey={activeItemKey}
              sortBy={filters.sortBy ?? "timestamp"}
              sortOrder={filters.sortOrder ?? "desc"}
              onSort={handleSort}
            />
          ) : null}

          {/* Pagination */}
          {queueData && queueData.total > 0 && (
            <div className="flex items-center justify-between mt-4 text-xs text-muted-foreground">
              <span>
                Showing {(queueData.page - 1) * queueData.pageSize + 1}–
                {Math.min(
                  queueData.page * queueData.pageSize,
                  queueData.total
                )}{" "}
                of {queueData.total}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={queueData.page <= 1}
                  onClick={() =>
                    setFilters((prev) => ({
                      ...prev,
                      page: Math.max(1, (prev.page ?? 1) - 1),
                    }))
                  }
                >
                  Previous
                </Button>
                <span className="px-2">
                  Page {queueData.page} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={queueData.page >= totalPages}
                  onClick={() =>
                    setFilters((prev) => ({
                      ...prev,
                      page: (prev.page ?? 1) + 1,
                    }))
                  }
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Bulk actions bar */}
      <BulkActionsBar
        selectedCount={selectedIds.size}
        onApproveAll={handleApproveAll}
        onFlagForDiscussion={handleFlagAll}
        onClearSelection={() => setSelectedIds(new Set())}
        isPending={bulkAction.isPending}
      />

      {/* Review Detail Panel */}
      <ReviewDetailPanel
        open={isPanelOpen}
        evaluation={detailData?.evaluation ?? null}
        existingReview={detailData?.existingReview ?? null}
        runId={detailRunId}
        isLoading={detailLoading}
        onClose={() => setIsPanelOpen(false)}
        onSave={async (review: HumanReview) => {
          try {
            await saveReview.mutateAsync({
              runId: review.runId,
              turnId: review.turnId,
              review: review as unknown as Record<string, unknown>,
            });
            queryClient.invalidateQueries({ queryKey: ["review-queue"] });
            queryClient.invalidateQueries({ queryKey: ["review-stats"] });
          } catch {
            // handled by mutation state
          }
        }}
      />
    </div>
  );
}
