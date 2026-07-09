"use client";

import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Menu, RefreshCw } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

const ROUTE_LABELS: Record<string, string> = {
  "/monitor": "Monitor",
  "/review": "Review Queue",
  "/golden-dataset": "Golden Dataset",
};

interface HeaderProps {
  onToggleSidebar?: () => void;
}

export function Header({ onToggleSidebar }: HeaderProps) {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  // Track query data timestamps to show "last updated"
  useEffect(() => {
    const unsubscribe = queryClient.getQueryCache().subscribe(() => {
      const queries = queryClient.getQueryCache().getAll();
      const timestamps = queries
        .map((q) => q.state.dataUpdatedAt)
        .filter(Boolean) as number[];
      if (timestamps.length > 0) {
        setLastUpdated(Math.max(...timestamps));
      }
    });
    return () => unsubscribe();
  }, [queryClient]);

  const breadcrumb = ROUTE_LABELS[pathname] || pathname.split("/").pop() || "Dashboard";

  function handleRefresh() {
    queryClient.invalidateQueries();
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-header-bg px-4 shrink-0">
      <div className="flex items-center gap-3">
        {/* Mobile menu button */}
        <Button
          variant="ghost"
          size="icon-sm"
          className="lg:hidden"
          onClick={onToggleSidebar}
          aria-label="Toggle sidebar"
        >
          <Menu className="h-4 w-4" />
        </Button>

        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb">
          <span className="text-sm font-medium text-foreground">
            {breadcrumb}
          </span>
        </nav>
      </div>

      <div className="flex items-center gap-3">
        {lastUpdated && (
          <span className="text-xs text-muted-foreground hidden sm:inline">
            Updated {formatDistanceToNow(lastUpdated, { addSuffix: true })}
          </span>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          aria-label="Refresh data"
        >
          <RefreshCw className="h-4 w-4 mr-1.5" />
          <span className="hidden sm:inline">Refresh</span>
        </Button>
      </div>
    </header>
  );
}
