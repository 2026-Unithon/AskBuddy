"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AppProvider } from "@/lib/store";
import { ApiError } from "@/lib/api";
import { SessionExpiryHandler } from "@/components/session-expiry-handler";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: true,
            refetchOnReconnect: true,
            retry: (failureCount, error) => {
              if (error instanceof ApiError) return error.retryable && failureCount < 2;
              return failureCount < 2;
            },
            retryDelay: (attempt, error) =>
              error instanceof ApiError && error.retryAfterMs !== null
                ? Math.min(error.retryAfterMs, 30_000)
                : Math.min(1_000 * 2 ** attempt, 8_000),
          },
          mutations: { retry: false },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <SessionExpiryHandler />
        {children}
      </AppProvider>
    </QueryClientProvider>
  );
}
