"use client";

import { useEffect, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { X, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

interface Toast {
  id: string;
  message: string;
  type: "success" | "warning" | "error";
}

let addToastFn: ((toast: Omit<Toast, "id">) => void) | null = null;

export function toast(message: string, type: Toast["type"] = "success") {
  addToastFn?.({ message, type });
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((t: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { ...t, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 3500);
  }, []);

  useEffect(() => {
    addToastFn = addToast;
    return () => {
      addToastFn = null;
    };
  }, [addToast]);

  function dismiss(id: string) {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }

  if (toasts.length === 0) return null;

  const iconMap = {
    success: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
    warning: <AlertTriangle className="h-4 w-4 text-amber-400" />,
    error: <XCircle className="h-4 w-4 text-red-400" />,
  };

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={cn(
            "flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 shadow-lg text-sm animate-in",
            "slide-in-from-right-4"
          )}
        >
          {iconMap[t.type]}
          <span className="flex-1 text-foreground text-xs">{t.message}</span>
          <button
            type="button"
            onClick={() => dismiss(t.id)}
            className="text-muted-foreground hover:text-foreground shrink-0"
            aria-label="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
