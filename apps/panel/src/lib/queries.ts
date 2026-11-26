import {
  type QueryClient,
  type QueryKey,
  queryOptions,
} from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";

/** Every react-query key in one place, so a typo cannot silently stop an
 * invalidation from matching. Keys of one entity share their first element. */
export const qk = {
  me: () => ["me"] as const,
  overview: () => ["overview"] as const,
  system: () => ["system"] as const,
  systemConfig: () => ["system", "config"] as const,
  tenants: () => ["tenants"] as const,
  tenant: (slug: string) => ["tenant", slug] as const,
  tenantSummary: (slug: string) => ["tenant-summary", slug] as const,
  tenantSetup: (slug: string) => ["tenant-setup", slug] as const,
  /** Results of «Comprobar» and of step actions (see lib/setup-checks.ts). Not
   * tenant-scoped on purpose: an invalidation or a reload must not drop them. */
  setupChecks: (slug: string) => ["setup-checks", slug] as const,
  tenantSecrets: (slug: string) => ["tenant-secrets", slug] as const,
  tenantWebhook: (slug: string) => ["tenant-webhook", slug] as const,
  tenantVersions: (slug: string) => ["tenant-versions", slug] as const,
  tenantVersion: (slug: string, version: unknown) =>
    ["tenant-version", slug, version] as const,
  tenantDataset: (slug: string, dataset: string) =>
    ["tenant-dataset", slug, dataset] as const,
  activationChecklist: (slug: string) =>
    ["activation-checklist", slug] as const,
  contacts: (slug: string) => ["contacts", slug] as const,
  contactsSearch: (slug: string, search: string) =>
    ["contacts", slug, search] as const,
  contact: (id: string | null) => ["contact", id] as const,
  notifications: (slug: string) => ["notifications", slug] as const,
  packs: () => ["packs"] as const,
  packSchema: (pack: string) => ["pack-schema", pack] as const,
  packTemplate: (pack: string) => ["pack-template", pack] as const,
  datasetLibrary: (pack: string, dataset: string) =>
    ["dataset-library", pack, dataset] as const,
  slugAvailability: (slug: string) => ["slug-availability", slug] as const,
  calendarServiceAccount: () => ["calendar-service-account"] as const,
  /** The open incidents; `incidentsHistory` and `incidentCases` share its first
   * element, so invalidating `incidents()` refreshes all three. */
  incidents: () => ["incidents"] as const,
  incidentsHistory: () => ["incidents", "history"] as const,
  incidentCases: (id: string) => ["incidents", "cases", id] as const,
  activity: (tenant: string, kinds: string, status: string) =>
    ["activity", tenant, kinds, status] as const,
  activityAll: () => ["activity"] as const,
  activityDetail: (kind: string, id: string) =>
    ["activity-detail", kind, id] as const,
  demoInvites: () => ["demo-invites"] as const,
  demoInviteQr: (id: string) => ["demo-invite-qr", id] as const,
  dataTables: () => ["data-tables"] as const,
  dataTable: (table: string) => ["data-table", table] as const,
  logs: (filters: unknown) => ["logs", filters] as const,
  auditActions: () => ["audit-actions"] as const,
  audit: (tenant: string, action: string) => ["audit", tenant, action] as const,
};

export function invalidateKeys(client: QueryClient, keys: readonly QueryKey[]) {
  for (const queryKey of keys) void client.invalidateQueries({ queryKey });
}

/** Live queries: refetched every 30 s while the tab is visible. Spread it into the
 * options of anything that shows data other people or the backend change on their
 * own. Never into: setup steps, the Telegram webhook status (every read calls
 * Telegram), logs, console/audit results, version previews or QR images. */
export const LIVE_REFETCH_MS = 30_000;
export const LIVE = {
  refetchInterval: LIVE_REFETCH_MS,
  refetchIntervalInBackground: false,
} as const;

/** `LIVE` for infinite lists: a refetch reloads every loaded page, so polling stops
 * as soon as the operator has scrolled past the first one. */
export const LIVE_FIRST_PAGE = {
  refetchInterval: (query: { state: { data?: unknown } }) => {
    const pages = (query.state.data as { pages?: unknown[] } | undefined)
      ?.pages;
    return (pages?.length ?? 0) > 1 ? false : LIVE_REFETCH_MS;
  },
  refetchIntervalInBackground: false,
} as const;

/** First element of every key whose second element is a tenant slug. */
const TENANT_SCOPED = new Set([
  "tenant",
  "tenant-setup",
  "tenant-secrets",
  "tenant-webhook",
  "tenant-versions",
  "tenant-version",
  "tenant-dataset",
  "tenant-summary",
  "activation-checklist",
  "contacts",
  "notifications",
  "activity",
  "audit",
]);

/** Cross-tenant views that show data of a tenant. */
const TENANT_VIEWS: readonly QueryKey[] = [
  qk.tenants(),
  qk.overview(),
  qk.incidents(),
  qk.system(),
];

/** Does this query key hold data of tenant `slug`? (`activity` / `audit` take ""
 * for "every tenant", which includes this one.) */
export function isTenantKey(queryKey: QueryKey, slug: string): boolean {
  const [scope, who] = queryKey;
  return (
    typeof scope === "string" &&
    TENANT_SCOPED.has(scope) &&
    (who === slug ||
      ((scope === "activity" || scope === "audit") && who === ""))
  );
}

/** The one rule after any write on a tenant: everything of that tenant and the
 * cross-tenant views that show it are stale. The Telegram webhook status is only
 * refreshed when the write is about the channel (`channel`), because reading it
 * calls Telegram. «Comprobar» results live under `setup-checks`, which is not
 * tenant-scoped, so they are not touched here. */
export function invalidateTenantEverything(
  client: QueryClient,
  slug: string,
  { channel = false }: { channel?: boolean } = {},
) {
  void client.invalidateQueries({
    predicate: ({ queryKey }) =>
      isTenantKey(queryKey, slug) &&
      (channel || queryKey[0] !== qk.tenantWebhook(slug)[0]),
  });
  invalidateKeys(client, TENANT_VIEWS);
}

/** After deleting a tenant: drop everything cached about it (nothing to refetch)
 * and refresh the views that listed it. */
export function removeTenantQueries(client: QueryClient, slug: string) {
  client.removeQueries({
    predicate: ({ queryKey }) =>
      isTenantKey(queryKey, slug) ||
      (queryKey[0] === qk.setupChecks(slug)[0] && queryKey[1] === slug),
  });
}

/** ... after deleting a tenant. */
export const tenantRemoved = (): QueryKey[] => [
  qk.tenants(),
  qk.overview(),
  qk.incidents(),
  qk.system(),
];

export const tenantsQueryOptions = () =>
  queryOptions({
    queryKey: qk.tenants(),
    ...LIVE,
    queryFn: () => unwrap(api.GET("/tenants")),
  });

export const packSchemaQueryOptions = (pack: string) =>
  queryOptions({
    queryKey: qk.packSchema(pack),
    queryFn: () =>
      unwrap(api.GET("/packs/{pack}/schema", { params: { path: { pack } } })),
  });

export const packsQueryOptions = () =>
  queryOptions({
    queryKey: qk.packs(),
    queryFn: () => unwrap(api.GET("/packs")),
  });
