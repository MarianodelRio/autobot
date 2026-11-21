import { queryOptions } from "@tanstack/react-query";
import { qk } from "@/lib/queries";
import { fetchMe } from "./api";

export const meQueryOptions = queryOptions({
  queryKey: qk.me(),
  queryFn: fetchMe,
  retry: false,
});
