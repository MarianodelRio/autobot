import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import type { components } from "@/api/schema";
import {
  overlaySteps,
  recordSetupResult,
  useSetupChecks,
} from "@/lib/setup-checks";

type Step = components["schemas"]["SetupStepOut"];
const step = (key: string, detail: string): Step => ({
  key,
  section: "channel",
  label: key,
  why: "",
  state: "ok",
  blocking: false,
  detail,
  values: [],
  tester_candidates: [],
  checkable: true,
});

test("a stored result replaces the step only for the version it was obtained with", () => {
  const client = new QueryClient();
  recordSetupResult(client, "a", step("health", "comprobado"), 3);
  const checks = client.getQueryData(["setup-checks", "a"]) as never;
  const backend = [step("health", "sin comprobar"), step("doc", "ok")];
  expect(overlaySteps(backend, checks, 3).map((s) => s.detail)).toEqual([
    "comprobado",
    "ok",
  ]);
  expect(overlaySteps(backend, checks, 4).map((s) => s.detail)).toEqual([
    "sin comprobar",
    "ok",
  ]);
});

test("results are kept per step and per tenant", () => {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  recordSetupResult(client, "a", step("health", "uno"), 1);
  recordSetupResult(client, "a", step("webhook", "dos"), 1);
  recordSetupResult(client, "b", step("health", "otro"), 1);
  const a = renderHook(() => useSetupChecks("a"), { wrapper }).result.current;
  expect(Object.keys(a).sort()).toEqual(["health", "webhook"]);
  const b = renderHook(() => useSetupChecks("b"), { wrapper }).result.current;
  expect(b.health?.step.detail).toBe("otro");
  expect(
    renderHook(() => useSetupChecks("c"), { wrapper }).result.current,
  ).toEqual({});
});
