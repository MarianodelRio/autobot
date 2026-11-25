import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test, vi } from "vitest";
import { confirmApplied } from "@/lib/config-applied";
import {
  invalidateTenantEverything,
  isTenantKey,
  LIVE,
  qk,
} from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";

vi.mock("@/lib/config-applied", () => ({ confirmApplied: vi.fn() }));

const tenantKeys = (slug: string) => [
  qk.tenant(slug),
  qk.tenantSetup(slug),
  qk.tenantSecrets(slug),
  qk.tenantWebhook(slug),
  qk.tenantVersions(slug),
  qk.tenantVersion(slug, 3),
  qk.tenantDataset(slug, "horarios"),
  qk.tenantSummary(slug),
  qk.activationChecklist(slug),
  qk.contacts(slug),
  qk.contactsSearch(slug, "ana"),
  qk.notifications(slug),
  qk.activity(slug, "", ""),
  qk.audit(slug, ""),
];
const views = [
  qk.tenants(),
  qk.overview(),
  qk.incidents(),
  qk.alerts(),
  qk.system(),
];

test("isTenantKey matches every tenant-scoped key of the slug only", () => {
  for (const key of tenantKeys("a")) {
    expect(isTenantKey(key, "a")).toBe(true);
    expect(isTenantKey(key, "b")).toBe(false);
  }
  expect(isTenantKey(qk.activity("", "", ""), "a")).toBe(true);
  expect(isTenantKey(qk.tenants(), "a")).toBe(false);
  expect(isTenantKey(qk.packs(), "a")).toBe(false);
});

function seeded() {
  const client = new QueryClient();
  for (const key of [...tenantKeys("a"), ...tenantKeys("b"), ...views])
    client.setQueryData(key, 1);
  return client;
}
const stale = (client: QueryClient, key: readonly unknown[]) =>
  client.getQueryState(key)?.isInvalidated;

test("invalidateTenantEverything refreshes the tenant and the views, not others", () => {
  const client = seeded();
  invalidateTenantEverything(client, "a");
  for (const key of [...tenantKeys("a"), ...views])
    expect(stale(client, key)).toBe(true);
  for (const key of tenantKeys("b")) expect(stale(client, key)).toBe(false);
});

test("keepSetup leaves the setup steps alone", () => {
  const client = seeded();
  invalidateTenantEverything(client, "a", { keepSetup: true });
  expect(stale(client, qk.tenantSetup("a"))).toBe(false);
  expect(stale(client, qk.tenant("a"))).toBe(true);
});

test("useApiMutation with `tenant` applies the rule", async () => {
  const client = seeded();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () => useApiMutation({ fn: async () => "ok", tenant: "a" }),
    { wrapper },
  );
  result.current.mutate();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(stale(client, qk.tenantSetup("a"))).toBe(true);
  expect(stale(client, qk.tenants())).toBe(true);
  expect(stale(client, qk.tenant("b"))).toBe(false);
});

test("LIVE polls every 30 s only while the tab is visible", () => {
  expect(LIVE).toEqual({
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
});

async function runMutation(options: {
  tenant?: string;
  appliesConfig?: boolean;
}) {
  vi.mocked(confirmApplied).mockClear();
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () => useApiMutation({ fn: async () => "ok", ...options }),
    { wrapper },
  );
  result.current.mutate();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
}

test("a tenant write asks for the «applied in N processes» confirmation", async () => {
  await runMutation({ tenant: "a" });
  expect(confirmApplied).toHaveBeenCalledTimes(1);
});

test("writes that leave the configuration alone, or have no tenant, do not", async () => {
  await runMutation({ tenant: "a", appliesConfig: false });
  await runMutation({});
  expect(confirmApplied).not.toHaveBeenCalled();
});
