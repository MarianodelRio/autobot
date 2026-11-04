import { queryOptions, useQuery } from "@tanstack/react-query";
import { fetchMe } from "./api";

export const meQueryOptions = queryOptions({
  queryKey: ["me"],
  queryFn: fetchMe,
  retry: false,
});

export function useMe() {
  return useQuery(meQueryOptions);
}
