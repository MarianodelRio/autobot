import {
  type QueryKey,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { errorDetail } from "@/lib/errors";
import { invalidateKeys } from "@/lib/queries";

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
  onSuccess,
  onError,
}: {
  fn: (variables: V) => Promise<T>;
  success?: Resolvable<T, V, string>;
  /** Fallback text of the error toast (the backend's message wins). */
  error?: string;
  invalidate?: Resolvable<T, V, readonly QueryKey[]>;
  onSuccess?: (data: T, variables: V) => void;
  onError?: (err: unknown) => void;
}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data, variables) => {
      if (success) toast.success(resolve(success, data, variables));
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
