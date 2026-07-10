"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { BarChart3 } from "lucide-react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { NAV_ITEMS } from "@/components/layout/navigation-items";

interface SidebarProps {
  mobileOpen: boolean;
  onMobileClose: () => void;
  desktopCollapsed: boolean;
}

export function Sidebar({ mobileOpen, onMobileClose, desktopCollapsed }: SidebarProps) {
  const pathname = usePathname();

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
          <div className="flex h-8 w-8 items-center justify-center rounded-2xl bg-primary/14 text-primary">
            <BarChart3 className="h-4.5 w-4.5 shrink-0" />
          </div>
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
                  "flex items-center gap-3 rounded-2xl px-2.5 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/16 hover:text-sidebar-foreground",
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
      </aside>
    </>
  );
}
