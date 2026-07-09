"use client";

import { cn } from "@/lib/utils";
import type { ReviewStats } from "@/types/evaluation";
import {
  FileText,
  CheckCircle2,
  Edit3,
  AlertTriangle,
} from "lucide-react";

interface ReviewStatsBarProps {
  stats: ReviewStats | undefined;
  isLoading: boolean;
}

export function ReviewStatsBar({ stats, isLoading }: ReviewStatsBarProps) {
  const items = [
    {
      label: "Total Records",
      value: stats?.totalRecords ?? 0,
      icon: FileText,
      color: "text-muted-foreground",
    },
    {
      label: "Reviewed",
      value: stats?.reviewedCount ?? 0,
      icon: CheckCircle2,
      color: "text-emerald-400",
    },
    {
      label: "Drafts",
      value: stats?.draftCount ?? 0,
      icon: Edit3,
      color: "text-amber-400",
    },
    {
      label: "Disputed",
      value: stats?.disputedCount ?? 0,
      icon: AlertTriangle,
      color: "text-red-400",
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
      {items.map(({ label, value, icon: Icon, color }) => (
        <div
          key={label}
          className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3"
        >
          <Icon className={cn("h-5 w-5 shrink-0", color)} />
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground truncate">
              {label}
            </div>
            <div className="text-lg font-bold text-foreground tabular-nums">
              {isLoading ? "—" : value.toLocaleString()}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
