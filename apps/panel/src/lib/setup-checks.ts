import { type QueryClient, skipToken, useQuery } from "@tanstack/react-query";
import type { components } from "@/api/schema";
import { qk } from "@/lib/queries";

type SetupStep = components["schemas"]["SetupStepOut"];

/** A step result (from «Comprobar» or a step action) and the configuration version
 * of the tenant when it was obtained. */
type Stored = { version: number | null; step: SetupStep };
type Checks = Record<string, Stored>;

const NONE: Checks = {};

/** The backend never returns «Comprobar» results (they call Meta, Telegram or
 * Google), so they cannot come back from a refetch. They are kept apart from the
 * setup GET, under `setup-checks`, which no invalidation touches: a tenant write,
 * a tab switch or «Recargar» refetch the steps without losing them. A result is
 * shown only while the tenant's configuration version is the one it was obtained
 * with; a save that changes it makes the result stale, and it stops showing. */
export function useSetupChecks(slug: string): Checks {
  const { data } = useQuery({
    queryKey: qk.setupChecks(slug),
    // Never fetched: the cache is only written by hand.
    queryFn: skipToken,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });
  return (data as Checks | undefined) ?? NONE;
}

/** Remember a step result against the configuration `version` the tenant had when
 * it was obtained (the one on screen: checks run against what is saved). */
export function recordSetupResult(
  client: QueryClient,
  slug: string,
  step: SetupStep,
  version: number | null | undefined,
) {
  client.setQueryData<Checks>(qk.setupChecks(slug), (previous) => ({
    ...previous,
    [step.key]: { version: version ?? null, step },
  }));
}

/** The steps read from the backend, with the stored results of the current version
 * laid over them. */
export function overlaySteps(
  steps: SetupStep[],
  checks: Checks,
  version: number | null | undefined,
): SetupStep[] {
  const current = version ?? null;
  return steps.map((step) => {
    const stored = checks[step.key];
    return stored && stored.version === current ? stored.step : step;
  });
}
