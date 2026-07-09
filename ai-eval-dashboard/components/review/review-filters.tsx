"use client";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Search, X } from "lucide-react";
import type { ReviewQueueFilters, RunSummary } from "@/types/evaluation";

interface ReviewFiltersProps {
  filters: ReviewQueueFilters;
  onChange: (filters: ReviewQueueFilters) => void;
  runs: RunSummary[];
}

export function ReviewFilters({ filters, onChange, runs }: ReviewFiltersProps) {
  function set(key: keyof ReviewQueueFilters, value: unknown) {
    onChange({ ...filters, [key]: value || undefined });
  }

  function clearFilters() {
    onChange({ page: 1, pageSize: 50 });
  }

  const hasActiveFilters =
    filters.status ||
    filters.runId ||
    filters.searchText ||
    filters.disputedOnly ||
    filters.unreviewedOnly;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      {/* Status filter */}
      <Select
        value={filters.status || "all"}
        onValueChange={(v) =>
          set("status", v === "all" ? undefined : v)
        }
      >
        <SelectTrigger className="h-8 w-[130px] text-xs">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Status</SelectItem>
          <SelectItem value="pass">Pass</SelectItem>
          <SelectItem value="warn">Warn</SelectItem>
          <SelectItem value="fail">Fail</SelectItem>
        </SelectContent>
      </Select>

      {/* Run filter */}
      <Select
        value={filters.runId || "all"}
        onValueChange={(v) =>
          set("runId", v === "all" ? undefined : v)
        }
      >
        <SelectTrigger className="h-8 w-[160px] text-xs">
          <SelectValue placeholder="Run" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Runs</SelectItem>
          {runs.map((run) => (
            <SelectItem key={run.runId} value={run.runId}>
              {run.runId.length > 24
                ? run.runId.slice(0, 24) + "…"
                : run.runId}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Search */}
      <div className="relative flex-1 min-w-[180px]">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search user or response text…"
          value={filters.searchText || ""}
          onChange={(e) => set("searchText", e.target.value || undefined)}
          className="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 placeholder:text-muted-foreground"
        />
      </div>

      {/* Toggles */}
      <Button
        variant={filters.unreviewedOnly ? "secondary" : "outline"}
        size="sm"
        className="h-8 text-xs"
        onClick={() =>
          set("unreviewedOnly", !filters.unreviewedOnly || undefined)
        }
      >
        Unreviewed
      </Button>
      <Button
        variant={filters.disputedOnly ? "secondary" : "outline"}
        size="sm"
        className="h-8 text-xs"
        onClick={() =>
          set("disputedOnly", !filters.disputedOnly || undefined)
        }
      >
        Disputed
      </Button>

      {/* Clear */}
      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-xs"
          onClick={clearFilters}
        >
          <X className="h-3.5 w-3.5 mr-1" />
          Clear
        </Button>
      )}
    </div>
  );
}
