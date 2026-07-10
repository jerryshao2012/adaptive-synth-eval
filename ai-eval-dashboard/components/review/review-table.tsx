"use client";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { MetricBadge } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown, ChevronUp, ChevronDown } from "lucide-react";
import { format, parseISO } from "date-fns";
import type { ReviewQueueItem, ReviewQueueFilters } from "@/types/evaluation";

interface ReviewTableProps {
  items: ReviewQueueItem[];
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
  onRowClick: (item: ReviewQueueItem) => void;
  activeItemKey: string | null;
  sortBy: ReviewQueueFilters["sortBy"];
  sortOrder: ReviewQueueFilters["sortOrder"];
  onSort: (key: NonNullable<ReviewQueueFilters["sortBy"]>) => void;
}

function rowKey(item: ReviewQueueItem): string {
  return `${item.runId}:${item.conversationId}:${item.turnId}:${item.timestamp}`;
}

export function ReviewTable({
  items,
  selectedIds,
  onSelectionChange,
  onRowClick,
  activeItemKey,
  sortBy,
  sortOrder,
  onSort,
}: ReviewTableProps) {
  const allSelected =
    items.length > 0 && items.every((item) => selectedIds.has(rowKey(item)));
  const someSelected = items.some((item) => selectedIds.has(rowKey(item)));

  function toggleAll() {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(items.map(rowKey)));
    }
  }

  function toggleOne(key: string) {
    const next = new Set(selectedIds);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onSelectionChange(next);
  }

  function SortIcon({ column }: { column: NonNullable<ReviewQueueFilters["sortBy"]> }) {
    if (sortBy !== column) {
      return <ArrowUpDown className="h-3 w-3 text-muted-foreground/50" />;
    }
    return sortOrder === "asc" ? (
      <ChevronUp className="h-3 w-3" />
    ) : (
      <ChevronDown className="h-3 w-3" />
    );
  }

  function SortHeader({
    column,
    label,
    className,
  }: {
    column: NonNullable<ReviewQueueFilters["sortBy"]>;
    label: string;
    className?: string;
  }) {
    return (
      <button
        type="button"
        className={cn(
          "flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors",
          className
        )}
        onClick={() => onSort(column)}
      >
        {label}
        <SortIcon column={column} />
      </button>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            <th className="w-10 px-3 py-2.5 text-left" scope="col">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected && !allSelected;
                }}
                onChange={toggleAll}
                aria-label="Select all rows"
                className="h-3.5 w-3.5 rounded border-border"
              />
            </th>
            <th className="px-3 py-2.5 text-left" scope="col">
              <SortHeader column="timestamp" label="Timestamp" />
            </th>
            <th className="px-3 py-2.5 text-left" scope="col">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                User Message
              </span>
            </th>
            <th className="px-3 py-2.5 text-left" scope="col">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Response
              </span>
            </th>
            <th className="px-3 py-2.5 text-center" scope="col">
              <SortHeader column="safetyStatus" label="Safety" />
            </th>
            <th className="px-3 py-2.5 text-center" scope="col">
              <SortHeader column="safetyStatus" label="Perf." />
            </th>
            <th className="px-3 py-2.5 text-center" scope="col">
              <SortHeader column="avgAiScore" label="AI Score" />
            </th>
            <th className="px-3 py-2.5 text-center" scope="col">
              <SortHeader column="reviewStatus" label="Review" />
            </th>
            <th className="px-3 py-2.5 text-left" scope="col">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Flags
              </span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => {
            const key = rowKey(item);
            const isSelected = selectedIds.has(key);
            const isActive = key === activeItemKey;

            return (
              <tr
                key={key}
                onClick={() => onRowClick(item)}
                className={cn(
                  "transition-colors cursor-pointer",
                  isActive
                    ? "bg-accent"
                    : isSelected
                      ? "bg-primary/5"
                      : "hover:bg-muted/30"
                )}
              >
                <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleOne(key)}
                    aria-label={`Select row ${item.turnId}`}
                    className="h-3.5 w-3.5 rounded border-border"
                  />
                </td>
                <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap font-mono">
                  {format(parseISO(item.timestamp), "MMM d HH:mm")}
                </td>
                <td className="px-3 py-2.5 max-w-[180px]">
                  <Tooltip>
                    <TooltipTrigger>
                      <span className="line-clamp-1 text-foreground">
                        {item.userText}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-[360px] text-xs">
                      {item.userText}
                    </TooltipContent>
                  </Tooltip>
                </td>
                <td className="px-3 py-2.5 max-w-[180px]">
                  <Tooltip>
                    <TooltipTrigger>
                      <span className="line-clamp-1 text-foreground">
                        {item.responseText}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-[360px] text-xs">
                      {item.responseText}
                    </TooltipContent>
                  </Tooltip>
                </td>
                <td className="px-3 py-2.5 text-center">
                  <MetricBadge status={item.safetyStatus} />
                </td>
                <td className="px-3 py-2.5 text-center">
                  <MetricBadge status={item.performanceStatus} />
                </td>
                <td className="px-3 py-2.5 text-center font-mono tabular-nums font-medium">
                  {item.avgAiScore}%
                </td>
                <td className="px-3 py-2.5 text-center">
                  {item.reviewStatus && item.reviewStatus !== "none" ? (
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px]",
                        item.reviewStatus === "approved" &&
                          "border-emerald-400/40 text-emerald-400",
                        item.reviewStatus === "submitted" &&
                          "border-sky-400/40 text-sky-400",
                        item.reviewStatus === "draft" &&
                          "border-amber-400/40 text-amber-400"
                      )}
                    >
                      {item.reviewStatus}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  {item.flags.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {item.flags.map((flag) => (
                        <Badge
                          key={flag}
                          variant="outline"
                          className="text-[9px] px-1 py-0"
                        >
                          {flag}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
