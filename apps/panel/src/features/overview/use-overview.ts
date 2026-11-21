import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { qk } from "@/lib/queries";

export function useOverview() {
  return useQuery({
    queryKey: qk.overview(),
    queryFn: () => unwrap(api.GET("/overview")),
    refetchInterval: 30_000,
  });
}
