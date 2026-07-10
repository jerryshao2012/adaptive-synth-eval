"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { LayoutPanelLeft, Menu, RefreshCw } from "lucide-react";
import { NAV_ITEMS } from "@/components/layout/navigation-items";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface HeaderProps {
  onToggleSidebar?: () => void;
  desktopCollapsed?: boolean;
  onToggleDesktopSidebar?: () => void;
}

export function Header({
  onToggleSidebar,
  desktopCollapsed = false,
  onToggleDesktopSidebar,
}: HeaderProps) {
  const queryClient = useQueryClient();
  const isFetchingCount = useIsFetching();
  const pathname = usePathname();
  const [isNavigationMenuOpen, setNavigationMenuOpen] = useState(false);

  const lastUpdated = useMemo(() => {
    const timestamps = queryClient
      .getQueryCache()
      .getAll()
      .map((q) => q.state.dataUpdatedAt)
      .filter(Boolean) as number[];

    return timestamps.length > 0 ? Math.max(...timestamps) : null;
  }, [queryClient, isFetchingCount]);

  function handleRefresh() {
    queryClient.invalidateQueries();
  }

  function handleMenuClick() {
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches
    ) {
      setNavigationMenuOpen(true);
      return;
    }

    onToggleSidebar?.();
  }

  return (
    <>
      <header className="bmo-ai-shell flex h-14 items-center justify-between border-b border-border bg-header-bg px-4 shrink-0">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleMenuClick}
            aria-label="Open navigation menu"
            aria-haspopup="dialog"
            aria-expanded={isNavigationMenuOpen}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <div className="hidden lg:flex flex-col leading-none">
            <span className="text-sm font-semibold text-foreground">
              AI Eval Platform
            </span>
            <span className="text-xs text-muted-foreground">
              Monitor, review, and benchmark from one shell.
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {lastUpdated !== null && (
            <span className="hidden text-xs text-muted-foreground sm:inline">
              Updated {formatDistanceToNow(lastUpdated, { addSuffix: true })}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            aria-label="Refresh data"
          >
            <RefreshCw className="mr-1.5 h-4 w-4" />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </header>

      <Dialog open={isNavigationMenuOpen} onOpenChange={setNavigationMenuOpen}>
        <DialogContent
          className="max-w-[min(980px,calc(100%-2rem))] overflow-hidden rounded-[30px] border border-border/90 bg-popover/98 p-0 shadow-[0_24px_70px_rgba(5,15,30,0.24)] supports-backdrop-filter:backdrop-blur-xl"
          showCloseButton
        >
          <div className="grid gap-0 lg:grid-cols-[1.4fr_0.9fr]">
            <div className="border-b border-border/80 bg-[color-mix(in_oklab,var(--sidebar)_88%,transparent)] p-6 lg:border-r lg:border-b-0 dark:bg-[linear-gradient(180deg,rgba(23,59,74,0.96),rgba(7,9,13,0.94))]">
              <DialogHeader className="gap-3">
                <div className="inline-flex w-fit items-center rounded-full border border-primary/30 bg-primary/12 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.24em] text-primary dark:border-white/12 dark:bg-white/8 dark:text-white/78">
                  Navigation
                </div>
                <DialogTitle className="text-2xl text-sidebar-foreground dark:text-white">
                  Navigate the workspace
                </DialogTitle>
                <DialogDescription className="max-w-xl text-sm text-sidebar-foreground/70 dark:text-white/72">
                  Jump between live monitoring, review workflows, and golden
                  datasets without expanding the full rail.
                </DialogDescription>
              </DialogHeader>

              <div className="mt-6 grid gap-3 md:grid-cols-2">
                {NAV_ITEMS.map(({ href, label, description, icon: Icon }) => {
                  const isActive =
                    pathname === href ||
                    (href !== "/monitor" && pathname.startsWith(href));

                  return (
                    <Link
                      key={href}
                      href={href}
                      onClick={() => setNavigationMenuOpen(false)}
                      className={cn(
                        "group rounded-3xl border px-4 py-4 text-left transition-all",
                        isActive
                          ? "border-primary/40 bg-primary text-primary-foreground shadow-sm dark:border-white/20 dark:bg-white/16 dark:text-white"
                          : "border-border/80 bg-card/78 text-foreground hover:border-primary/30 hover:bg-background/78 dark:border-white/10 dark:bg-black/12 dark:text-white/88 dark:hover:border-white/20 dark:hover:bg-white/12"
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 rounded-2xl border border-primary/15 bg-primary/10 p-2.5 dark:border-white/12 dark:bg-white/10">
                          <Icon className="h-4 w-4" />
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">
                              {label}
                            </span>
                            {isActive && (
                              <span className="rounded-full border border-primary-foreground/20 bg-primary-foreground/12 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-primary-foreground/84 dark:border-white/18 dark:bg-white/12 dark:text-white/80">
                                Current
                              </span>
                            )}
                          </div>
                          <p className="text-sm leading-6 text-foreground/68 dark:text-white/68">
                            {description}
                          </p>
                        </div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </div>

            <div className="bg-popover p-6">
              <div className="space-y-6">
                <section className="space-y-3">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Appearance
                    </h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Switch themes without leaving the current view.
                    </p>
                  </div>
                  <ThemeToggle mode="panel" />
                </section>

                <section className="space-y-3 rounded-3xl border border-border/80 bg-card p-4 shadow-sm">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Sidebar
                    </h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Keep the rail compact by default, or pin the full
                      navigation labels.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    className="w-full justify-between"
                    onClick={onToggleDesktopSidebar}
                  >
                    <span>
                      {desktopCollapsed
                        ? "Pin expanded sidebar"
                        : "Collapse to icon rail"}
                    </span>
                    <LayoutPanelLeft className="h-4 w-4" />
                  </Button>
                </section>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}