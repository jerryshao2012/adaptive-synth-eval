"use client";

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(true);

  const toggleSidebar = useCallback(() => {
    setMobileOpen((prev) => !prev);
  }, []);

  const toggleDesktopSidebar = useCallback(() => {
    setDesktopCollapsed((prev) => !prev);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setMobileOpen(false);
  }, []);

  return (
    <div
      className={
        desktopCollapsed
          ? "dashboard-shell-collapsed flex h-full"
          : "dashboard-shell-expanded flex h-full"
      }
    >
      <Sidebar
        mobileOpen={mobileOpen}
        onMobileClose={closeMobileSidebar}
        desktopCollapsed={desktopCollapsed}
      />
      <div
        className={
          desktopCollapsed
            ? "flex flex-1 flex-col min-w-0 lg:ml-[56px]"
            : "flex flex-1 flex-col min-w-0 lg:ml-[220px]"
        }
      >
        <Header
          onToggleSidebar={toggleSidebar}
          desktopCollapsed={desktopCollapsed}
          onToggleDesktopSidebar={toggleDesktopSidebar}
        />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
