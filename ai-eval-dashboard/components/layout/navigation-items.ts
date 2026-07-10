import {
  Activity,
  ClipboardCheck,
  Database,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavigationItem[] = [
  {
    href: "/monitor",
    label: "Monitor",
    description: "Live quality signals, trace drill-down, and monitoring status.",
    icon: Activity,
  },
  {
    href: "/review",
    label: "Review Queue",
    description: "Triage flagged turns, compare scores, and apply review actions.",
    icon: ClipboardCheck,
  },
  {
    href: "/golden-dataset",
    label: "Golden Dataset",
    description: "Curate benchmark conversations and export evaluation baselines.",
    icon: Database,
  },
];