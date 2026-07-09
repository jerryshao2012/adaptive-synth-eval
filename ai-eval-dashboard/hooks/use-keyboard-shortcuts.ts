"use client";

import { useEffect } from "react";

interface Shortcut {
  key: string;
  ctrlOrMeta?: boolean;
  handler: () => void;
  enabled?: boolean;
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    function listener(event: KeyboardEvent) {
      for (const { key, ctrlOrMeta, handler, enabled } of shortcuts) {
        if (enabled === false) continue;

        const keyMatch = event.key.toLowerCase() === key.toLowerCase();
        const ctrlMatch = ctrlOrMeta
          ? event.ctrlKey || event.metaKey
          : !event.ctrlKey && !event.metaKey;

        if (keyMatch && ctrlMatch) {
          // Don't override browser save dialog
          if (ctrlOrMeta && key === "s") {
            event.preventDefault();
          }
          if (ctrlOrMeta && key === "enter") {
            event.preventDefault();
          }
          handler();
          return;
        }
      }
    }

    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [shortcuts]);
}
