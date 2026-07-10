"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000, // 30s before data is considered stale
            refetchInterval: 60_000, // auto-refetch every 60s
            retry: 2,
          },
        },
      })
  );
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const storedTheme = localStorage.getItem("ai-eval-theme");
    const resolvedTheme: Theme =
      storedTheme === "light" || storedTheme === "dark" ? storedTheme : "light";
    setTheme(resolvedTheme);
    applyTheme(resolvedTheme);
  }, []);

  useEffect(() => {
    localStorage.setItem("ai-eval-theme", theme);
    applyTheme(theme);
  }, [theme]);

  const themeValue = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => {
        setTheme((currentTheme) =>
          currentTheme === "dark" ? "light" : "dark"
        );
      },
    }),
    [theme]
  );

  return (
    <ThemeContext.Provider value={themeValue}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);

  if (!context) {
    throw new Error("useTheme must be used within Providers");
  }

  return context;
}
