import { QueryClient } from "@tanstack/react-query";
import type { ApiError } from "@/api/client";

function isClientError(error: unknown): boolean {
  const status = (error as ApiError | undefined)?.status;
  return typeof status === "number" && status >= 400 && status < 500;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => !isClientError(error) && failureCount < 1,
    },
  },
});
