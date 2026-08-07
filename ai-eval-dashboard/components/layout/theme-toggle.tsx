"use client";

import { Button } from "@/components/ui/button";
import { Sun, Moon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/components/providers";

interface ThemeToggleProps {
  mode?: "icon" | "panel";
  className?: string;
}

export function ThemeToggle({ mode = "icon", className }: ThemeToggleProps) {
  const { theme, setTheme, toggleTheme } = useTheme();

  if (mode === "panel") {
    return (
      <div className={cn("grid grid-cols-2 gap-3", className)}>
        <button
          type="button"
          onClick={() => setTheme("dark")}
          aria-label="Use dark theme"
          className={cn(
            "rounded-[24px] border p-3 text-left transition-all",
            theme === "dark"
              ? "border-primary ring-2 ring-primary/30 bg-accent/60 shadow-sm"
              : "border-border bg-card hover:border-primary/40 hover:bg-accent/40"
          )}
        >
          <div className="mb-3 overflow-hidden rounded-2xl border border-border/70 bg-[#0b0e12]">
            <div className="grid grid-cols-[0.26fr_1fr]">
              <div className="h-20 border-r border-white/10 bg-[#182f42]" />
              <div className="bg-[#07090d] p-3">
                <div className="h-2.5 w-4/5 rounded-full bg-white/10" />
                <div className="mt-2 h-2 w-3/5 rounded-full bg-white/8" />
                <div className="mt-4 h-7 rounded-2xl border border-white/10 bg-[#10151d]" />
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Moon className="h-4 w-4" />
              Dark
            </div>
            {theme === "dark" && <span className="text-xs text-primary">Selected</span>}
          </div>
        </button>
        <button
          type="button"
          onClick={() => setTheme("light")}
          aria-label="Use light theme"
          className={cn(
            "rounded-[24px] border p-3 text-left transition-all",
            theme === "light"
              ? "border-primary ring-2 ring-primary/30 bg-accent/60 shadow-sm"
              : "border-border bg-card hover:border-primary/40 hover:bg-accent/40"
          )}
        >
          <div className="mb-3 overflow-hidden rounded-2xl border border-border/70 bg-white">
            <div className="grid grid-cols-[0.26fr_1fr]">
              <div className="h-20 border-r border-slate-200 bg-[#f6f7fb]" />
              <div className="bg-white p-3">
                <div className="h-2.5 w-4/5 rounded-full bg-slate-200" />
                <div className="mt-2 h-2 w-3/5 rounded-full bg-slate-150 bg-slate-200/80" />
                <div className="mt-4 h-7 rounded-2xl border border-slate-200 bg-[#f8fafc]" />
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Sun className="h-4 w-4" />
              Light
            </div>
            {theme === "light" && <span className="text-xs text-primary">Selected</span>}
          </div>
        </button>
      </div>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      className={className}
      onClick={toggleTheme}
      aria-label="Toggle theme"
    >
      <Sun className="hidden h-4 w-4 dark:block" />
      <Moon className="h-4 w-4 dark:hidden" />
    </Button>
  );
}
