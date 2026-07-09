import { cn } from "@/lib/utils";
import { AlertCircle, BarChart3, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function EmptyState({
  message = "No evaluation data for this period.",
  suggestion = "Try widening the time range or check back later.",
  onAction,
  actionLabel,
}: {
  message?: string;
  suggestion?: string;
  onAction?: () => void;
  actionLabel?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="rounded-full bg-muted p-4 mb-4">
        <BarChart3 className="h-8 w-8 text-muted-foreground" />
      </div>
      <p className="text-lg font-medium text-foreground mb-1">{message}</p>
      <p className="text-sm text-muted-foreground max-w-sm">{suggestion}</p>
      {onAction && actionLabel && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onAction}>
          <RefreshCw className="mr-2 h-4 w-4" />
          {actionLabel}
        </Button>
      )}
    </div>
  );
}

export function ErrorCard({
  message = "Failed to load evaluation data.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="rounded-full bg-destructive/10 p-4 mb-4">
        <AlertCircle className="h-8 w-8 text-destructive" />
      </div>
      <p className="text-lg font-medium text-foreground mb-1">{message}</p>
      <p className="text-sm text-muted-foreground mb-4">
        Check your connection or try again.
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Retry
        </Button>
      )}
    </div>
  );
}

export function MetricBadge({
  status,
  className,
}: {
  status: "pass" | "warn" | "fail";
  className?: string;
}) {
  const colors: Record<string, string> = {
    pass: "bg-success/20 text-success border-success/30",
    warn: "bg-warning/20 text-warning border-warning/30",
    fail: "bg-destructive/20 text-destructive border-destructive/30",
  };

  const labels: Record<string, string> = {
    pass: "Pass",
    warn: "Warn",
    fail: "Fail",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        colors[status],
        className
      )}
    >
      {labels[status]}
    </span>
  );
}

export function TrendIndicator({
  value,
  label,
}: {
  value: number;
  label?: string;
}) {
  const isUp = value > 0;
  const isDown = value < 0;
  const isFlat = value === 0;

  return (
    <span className="inline-flex items-center gap-0.5 text-xs">
      {isUp && <span className="text-success">↑{value}%</span>}
      {isDown && <span className="text-destructive">↓{Math.abs(value)}%</span>}
      {isFlat && <span className="text-muted-foreground">→0%</span>}
      {label && (
        <span className="text-muted-foreground ml-0.5">{label}</span>
      )}
    </span>
  );
}
