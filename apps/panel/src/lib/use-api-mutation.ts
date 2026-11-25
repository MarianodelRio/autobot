import {
  type QueryKey,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { confirmApplied } from "@/lib/config-applied";
import { errorDetail } from "@/lib/errors";
import { invalidateKeys, invalidateTenantEverything } from "@/lib/queries";

type Resolvable<T, V, R> = R | ((data: T, variables: V) => R);

function resolve<T, V, R>(value: Resolvable<T, V, R>, data: T, vars: V): R {
  return typeof value === "function"
    ? (value as (data: T, variables: V) => R)(data, vars)
    : value;
}

/** useMutation plus the panel's usual feedback: a success toast, an error toast
 * with the backend's detail and the invalidation of the stale queries.
 * Omit `success` / `error` for no toast (the caller then shows the error inline). */
export function useApiMutation<T, V = void>({
  fn,
  success,
  error,
  invalidate,
  tenant,
  keepSetup,
  appliesConfig = true,
  onSuccess,
  onError,
}: {
  fn: (variables: V) => Promise<T>;
  success?: Resolvable<T, V, string>;
  /** Fallback text of the error toast (the backend's message wins). */
  error?: string;
  invalidate?: Resolvable<T, V, readonly QueryKey[]>;
  /** Slug of the tenant this write changes: everything of it (and the lists and
   * summaries that show it) is refreshed. Every tenant mutation must pass it. */
  tenant?: Resolvable<T, V, string>;
  /** With `tenant`: do not refetch the setup steps (see invalidateTenantEverything). */
  keepSetup?: boolean;
  /** With `tenant`: the write changes the tenant's configuration, so the panel
   * confirms «Aplicado en N procesos» (config-applied.ts). Pass `false` for writes
   * that leave the configuration alone (a health check, forgetting a contact). */
  appliesConfig?: boolean;
  onSuccess?: (data: T, variables: V) => void;
  onError?: (err: unknown) => void;
}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data, variables) => {
      if (success) toast.success(resolve(success, data, variables));
      if (tenant)
        invalidateTenantEverything(client, resolve(tenant, data, variables), {
          keepSetup,
        });
      if (tenant && appliesConfig) void confirmApplied();
      if (invalidate)
        invalidateKeys(client, resolve(invalidate, data, variables));
      onSuccess?.(data, variables);
    },
    onError: (err) => {
      if (error) toast.error(errorDetail(err, error));
      onError?.(err);
    },
  });
}
