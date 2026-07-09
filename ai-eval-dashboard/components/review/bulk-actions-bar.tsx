"use client";

import { Button } from "@/components/ui/button";
import { CheckCheck, Flag, X } from "lucide-react";

interface BulkActionsBarProps {
  selectedCount: number;
  onApproveAll: () => void;
  onFlagForDiscussion: () => void;
  onClearSelection: () => void;
  isPending: boolean;
}

export function BulkActionsBar({
  selectedCount,
  onApproveAll,
  onFlagForDiscussion,
  onClearSelection,
  isPending,
}: BulkActionsBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="sticky bottom-4 z-20 flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-lg mx-auto max-w-2xl">
      <span className="text-sm font-medium text-foreground">
        {selectedCount} row{selectedCount !== 1 ? "s" : ""} selected
      </span>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={onApproveAll}
          disabled={isPending}
          className="h-8 text-xs"
        >
          <CheckCheck className="h-3.5 w-3.5 mr-1.5" />
          Approve AI Scores
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onFlagForDiscussion}
          disabled={isPending}
          className="h-8 text-xs"
        >
          <Flag className="h-3.5 w-3.5 mr-1.5" />
          Flag
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={onClearSelection}
          aria-label="Clear selection"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
