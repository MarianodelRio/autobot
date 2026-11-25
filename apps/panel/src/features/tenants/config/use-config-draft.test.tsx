import { act, renderHook } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { useConfigDraft } from "./use-config-draft";

type Detail = components["schemas"]["TenantDetail"];
const detail = (document: Record<string, unknown>, version: number) =>
  ({ document, version }) as unknown as Detail;
const identity = (document: unknown) => document as never;

test("a background refetch does not overwrite a dirty draft, a clean one follows", () => {
  const { result, rerender } = renderHook(
    ({ d }) => useConfigDraft(d, vi.fn(), identity),
    { initialProps: { d: detail({ phone: "1" }, 1) } },
  );
  act(() => result.current.changeFields({ phone: "typed" }, ["phone"]));
  expect(result.current.dirty).toBe(true);
  rerender({ d: detail({ phone: "2" }, 2) });
  expect(result.current.draft).toEqual({ phone: "typed" });
  expect(result.current.version).toBe(1);
  act(() => result.current.discard());
  expect(result.current.dirty).toBe(false);
  rerender({ d: detail({ phone: "3" }, 3) });
  expect(result.current.draft).toEqual({ phone: "3" });
  expect(result.current.version).toBe(3);
});
