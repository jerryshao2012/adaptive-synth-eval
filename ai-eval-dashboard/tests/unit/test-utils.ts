import React from "react";
import { QueryClient, QueryClientProvider, type QueryClientConfig } from "@tanstack/react-query";
import { render } from "@testing-library/react";

type ResettableMock = {
  mockReset: () => unknown;
};

type ResolvableMock = ResettableMock & {
  mockResolvedValue: (value: unknown) => unknown;
};

export function renderWithDefaults<P extends object>(
  Component: React.ComponentType<P>,
  defaults: P,
  overrides: Partial<P> = {}
) {
  const props = { ...defaults, ...overrides } as P;
  return { ...render(React.createElement(Component, props)), props };
}

export function createTestQueryClient(config: QueryClientConfig = {}) {
  const queryDefaults = config.defaultOptions?.queries ?? {};
  return new QueryClient({
    defaultOptions: {
      ...config.defaultOptions,
      queries: {
        retry: false,
        gcTime: Infinity,
        ...queryDefaults,
      },
    },
    ...config,
  });
}

export function createQueryClientWrapper(client: QueryClient) {
  return function QueryClientWrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client }, children);
  };
}

export function resetMocks(mocks: ResettableMock[]) {
  mocks.forEach((mock) => mock.mockReset());
}

export function resetMocksWithResolvedValue(
  mocks: ResolvableMock[],
  resolvedValue: unknown
) {
  mocks.forEach((mock) => {
    mock.mockReset();
    mock.mockResolvedValue(resolvedValue);
  });
}
