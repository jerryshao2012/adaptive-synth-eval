"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  Activity,
  BarChart3,
  ClipboardCheck,
  Database,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { useState } from "react";

const NAV_ITEMS = [
  {
    href: "/monitor",
    label: "Monitor",
    icon: Activity,
  },
  {
    href: "/review",
    label: "Review Queue",
    icon: ClipboardCheck,
  },
  {
    href: "/golden-dataset",
    label: "Golden Dataset",
    icon: Database,
  },
] as const;

interface SidebarProps {
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const pathname = usePathname();
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);

  // On mobile: mobileOpen controls visibility. On desktop: always visible.
  const isVisible = mobileOpen; // mobile only
  const isWide = !desktopCollapsed;

  return (
    <>
      {/* Mobile overlay */}
      {isVisible && (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-30 bg-black/35 lg:hidden"
          onClick={onMobileClose}
        />
      )}

      <aside
        className={cn(
          "fixed top-0 bottom-0 left-0 z-40 flex flex-col border-r border-sidebar-border bg-sidebar transition-all duration-300 ease-out",
          // Mobile: slide in/out
          isVisible ? "translate-x-0" : "-translate-x-full",
          // Desktop: always translated in, width controlled by collapsed state
          "lg:translate-x-0",
          isWide ? "lg:w-[220px]" : "lg:w-[56px]"
        )}
      >
        {/* Branding */}
        <div
          className={cn(
            "flex h-14 items-center gap-2.5 border-b border-sidebar-border px-3.5 shrink-0",
            !isWide && "lg:justify-center lg:px-0"
          )}
        >
          <BarChart3 className="h-5 w-5 shrink-0 text-primary" />
          {isWide && (
            <span className="text-sm font-semibold text-sidebar-foreground truncate hidden lg:inline">
              AI Eval Platform
            </span>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 space-y-1 px-2 py-4" aria-label="Main navigation">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const isActive =
              pathname === href ||
              (href !== "/monitor" && pathname.startsWith(href));

            return (
              <Link
                key={href}
                href={href}
                onClick={onMobileClose}
                className={cn(
                  "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                  !isWide && "lg:justify-center lg:px-0"
                )}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon className="h-4.5 w-4.5 shrink-0" />
                {isWide && <span className="hidden lg:inline">{label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Theme toggle */}
        <div className="border-t border-sidebar-border p-2">
          <ThemeToggle />
        </div>

        {/* Desktop collapse toggle */}
        <div className="hidden lg:block border-t border-sidebar-border p-2">
          <Button
            variant="ghost"
            size="icon-sm"
            className="w-full text-sidebar-foreground/60 hover:text-sidebar-foreground"
            onClick={() => setDesktopCollapsed((prev) => !prev)}
            aria-label={desktopCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {desktopCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </Button>
        </div>
      </aside>
    </>
  );
}
