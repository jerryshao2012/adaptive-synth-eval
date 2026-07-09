"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  Database,
  Download,
  Eye,
  Archive,
  FileJson,
  FileSpreadsheet,
} from "lucide-react";
import { format, parseISO } from "date-fns";
import type { GoldenDataset } from "@/types/evaluation";

interface DatasetListProps {
  datasets: GoldenDataset[];
  isLoading: boolean;
  onView: (id: string) => void;
  onExport: (id: string, format: "jsonl" | "csv") => void;
  onArchive: (id: string) => void;
}

export function DatasetList({
  datasets,
  isLoading,
  onView,
  onExport,
  onArchive,
}: DatasetListProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i} className="border-border bg-card">
            <CardContent className="p-4">
              <Skeleton className="h-5 w-32 mb-3" />
              <Skeleton className="h-4 w-24 mb-2" />
              <Skeleton className="h-4 w-20" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (datasets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Database className="h-8 w-8 text-muted-foreground" />
        </div>
        <p className="text-lg font-medium text-foreground mb-1">
          No golden datasets yet
        </p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Create a golden dataset by selecting reviewed evaluation records.
        </p>
      </div>
    );
  }

  const statusColor: Record<string, string> = {
    draft: "border-amber-400/40 text-amber-400",
    published: "border-emerald-400/40 text-emerald-400",
    archived: "border-muted-foreground/40 text-muted-foreground",
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {datasets.map((ds) => (
        <Card
          key={ds.datasetId}
          className="border-border bg-card hover:border-[color-mix(in_srgb,var(--primary)_20%,transparent)] transition-colors"
        >
          <CardContent className="p-4">
            <div className="flex items-start justify-between mb-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-foreground truncate">
                  {ds.name}
                </h3>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="text-[10px] font-mono">
                    v{ds.version}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={cn("text-[10px]", statusColor[ds.status] || "")}
                  >
                    {ds.status}
                  </Badge>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 mb-3 text-xs text-muted-foreground">
              <div>
                <span className="font-medium text-foreground tabular-nums">
                  {ds.stats.totalRecords}
                </span>{" "}
                records
              </div>
              <div>
                <span className="font-medium text-foreground tabular-nums">
                  {ds.stats.reviewedCount}
                </span>{" "}
                reviewed
              </div>
              <div>
                <span className="font-medium text-foreground tabular-nums">
                  {ds.stats.interRaterAgreement}%
                </span>{" "}
                agreement
              </div>
              <div className="text-muted-foreground">
                {format(parseISO(ds.updatedAt), "MMM d, yyyy")}
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => onView(ds.datasetId)}
              >
                <Eye className="h-3.5 w-3.5 mr-1" />
                View
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => onExport(ds.datasetId, "jsonl")}
              >
                <FileJson className="h-3.5 w-3.5 mr-1" />
                JSONL
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => onExport(ds.datasetId, "csv")}
              >
                <FileSpreadsheet className="h-3.5 w-3.5 mr-1" />
                CSV
              </Button>
              {ds.status !== "archived" && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs ml-auto"
                  onClick={() => onArchive(ds.datasetId)}
                >
                  <Archive className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
