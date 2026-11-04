import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";

export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: () => unwrap(api.GET("/overview")),
    refetchInterval: 30_000,
  });
}
