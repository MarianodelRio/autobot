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
  tenants: () => ["tenants"] as const,
  tenant: (slug: string) => ["tenant", slug] as const,
  tenantSummary: (slug: string) => ["tenant-summary", slug] as const,
  tenantSetup: (slug: string) => ["tenant-setup", slug] as const,
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
  incidents: () => ["incidents"] as const,
  alerts: () => ["alerts"] as const,
  alertsResolved: () => ["alerts", "resolved"] as const,
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

/** Keys stale after editing one tenant: its detail and the Resumen screen. */
export const tenantChanged = (slug: string): QueryKey[] => [
  qk.tenant(slug),
  qk.overview(),
];
/** ... after its status changes: the list shows it too. */
export const tenantLifecycleChanged = (slug: string): QueryKey[] => [
  qk.tenant(slug),
  qk.tenants(),
  qk.overview(),
];
/** ... after deleting a tenant. */
export const tenantRemoved = (): QueryKey[] => [
  qk.tenants(),
  qk.overview(),
  qk.incidents(),
];

export const invalidateTenant = (client: QueryClient, slug: string) =>
  invalidateKeys(client, tenantChanged(slug));
export const invalidateTenantLifecycle = (client: QueryClient, slug: string) =>
  invalidateKeys(client, tenantLifecycleChanged(slug));

export const tenantsQueryOptions = () =>
  queryOptions({
    queryKey: qk.tenants(),
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
