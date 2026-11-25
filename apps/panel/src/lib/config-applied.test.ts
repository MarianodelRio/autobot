import { afterEach, beforeEach, expect, test, vi } from "vitest";

const toast = vi.hoisted(() => ({
  loading: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  dismiss: vi.fn(),
}));
const get = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast }));
vi.mock("@/api/client", () => ({
  api: { GET: get },
  unwrap: async (promise: Promise<unknown>) => promise,
}));

import { QueryClient } from "@tanstack/react-query";
import {
  confirmApplied,
  MAX_WAIT_MS,
  STALL_MS,
  summarize,
} from "@/lib/config-applied";
import { qk } from "@/lib/queries";

type P = { service: string; revision: number; last_error_at?: string | null };
const state = (revision: number, processes: P[]) => ({
  revision,
  updated_at: null,
  processes: processes.map((p, index) => ({
    host: "h",
    pid: index,
    started_at: "",
    seen_at: "",
    behind: p.revision < revision,
    ...p,
  })),
});

const client = new QueryClient();
const invalidate = vi.spyOn(client, "invalidateQueries");
const invalidatedTenant = () =>
  invalidate.mock.calls.some(([filters]) =>
    filters?.predicate?.({ queryKey: qk.tenant("a") } as never),
  );

beforeEach(() => {
  vi.useFakeTimers();
  for (const fn of Object.values(toast)) fn.mockReset();
  get.mockReset();
  invalidate.mockClear();
});
afterEach(() => vi.useRealTimers());

const done = state(5, [
  { service: "web", revision: 5 },
  { service: "worker-inbound", revision: 5 },
]);

test("summarize uses the API's behind flag, else a revision different from the target", () => {
  const s = summarize(
    state(5, [
      { service: "web", revision: 5 },
      { service: "worker-inbound", revision: 4 },
      { service: "worker-inbound", revision: 3 },
      { service: "web-panel", revision: 6 },
    ]),
    5,
  );
  // web-panel is ahead (a restore to an older version): its flag is false in this
  // fixture (behind = revision < target), so only the flag decides.
  expect(s).toMatchObject({ total: 4, applied: 2, behind: ["worker-inbound"] });
  const noFlag = {
    ...state(5, []),
    processes: [
      { service: "web", revision: 6 },
      { service: "w", revision: 5 },
    ],
  } as never;
  expect(summarize(noFlag, 5)).toMatchObject({ applied: 1, behind: ["web"] });
});

test("summarize names the services behind that also report an error", () => {
  const s = summarize(
    state(5, [
      { service: "web", revision: 4, last_error_at: "2026-11-25T10:00:00Z" },
    ]),
    5,
  );
  expect(s.failing).toEqual(["web"]);
});

test("confirms at once when every process already has the revision, and refreshes the tenant", async () => {
  get.mockResolvedValue(done);
  await confirmApplied(client, "a");
  expect(toast.loading).not.toHaveBeenCalled();
  expect(toast.success).toHaveBeenCalledWith("Aplicado en 2 procesos", {
    id: "config-applied",
    duration: 4000,
  });
  expect(invalidatedTenant()).toBe(true);
});

test("shows «Aplicando…» until the laggards catch up, then succeeds and refreshes once", async () => {
  const behind = state(5, [
    { service: "web", revision: 5 },
    { service: "worker-inbound", revision: 4 },
  ]);
  get.mockResolvedValueOnce(behind).mockResolvedValueOnce(behind);
  get.mockResolvedValue(done);
  const finished = confirmApplied(client, "a");
  await vi.advanceTimersByTimeAsync(2000);
  await finished;
  expect(toast.loading).toHaveBeenCalledWith("Aplicando el cambio…", {
    id: "config-applied",
  });
  expect(toast.success).toHaveBeenCalledTimes(1);
  expect(toast.warning).not.toHaveBeenCalled();
  expect(invalidatedTenant()).toBe(true);
});

test("keeps waiting past 10 s while processes keep progressing, up to the 30 s bound", async () => {
  // One more process catches up every 8 s (less than STALL_MS); one never does.
  let calls = 0;
  get.mockImplementation(async () => {
    const caughtUp = Math.floor((calls++ * 500) / 8000);
    return state(5, [
      { service: "web", revision: 5 },
      ...Array.from({ length: 5 }, (_, i) => ({
        service: i < caughtUp ? "ok" : "lag",
        revision: i < caughtUp ? 5 : 4,
      })),
    ]);
  });
  const finished = confirmApplied(client, "a");
  await vi.advanceTimersByTimeAsync(STALL_MS + 2000);
  expect(toast.warning).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(MAX_WAIT_MS);
  await finished;
  expect(toast.warning).toHaveBeenCalledTimes(1);
  expect(invalidatedTenant()).toBe(true);
});

test("warns with the services still behind once nothing progresses for 10 s", async () => {
  get.mockResolvedValue(
    state(5, [
      { service: "web", revision: 5 },
      { service: "worker-inbound", revision: 4 },
      {
        service: "worker-outbound",
        revision: 4,
        last_error_at: "2026-11-25T10:00:00Z",
      },
    ]),
  );
  const finished = confirmApplied(client, "a");
  await vi.advanceTimersByTimeAsync(STALL_MS + 1000);
  await finished;
  expect(toast.warning).toHaveBeenCalledWith(
    "Aplicado en 1 de 3; siguen con la versión anterior: worker-inbound, worker-outbound (con error)",
    { id: "config-applied", duration: 15000 },
  );
  expect(toast.success).not.toHaveBeenCalled();
  expect(invalidatedTenant()).toBe(true);
});

test("a newer save supersedes the one still polling", async () => {
  get.mockResolvedValue(state(5, [{ service: "web", revision: 4 }]));
  const first = confirmApplied(client, "a");
  await vi.advanceTimersByTimeAsync(600);
  get.mockResolvedValue(state(6, [{ service: "web", revision: 6 }]));
  const second = confirmApplied(client, "a");
  await vi.advanceTimersByTimeAsync(STALL_MS + 1000);
  await Promise.all([first, second]);
  expect(toast.warning).not.toHaveBeenCalled();
  expect(toast.success).toHaveBeenCalledTimes(1);
});

test("shows nothing when no process reports, and drops the toast on errors", async () => {
  get.mockResolvedValue(state(5, []));
  await confirmApplied(client, "a");
  expect(toast.dismiss).toHaveBeenCalledWith("config-applied");
  expect(toast.success).not.toHaveBeenCalled();
  toast.dismiss.mockReset();
  get.mockRejectedValue(new Error("down"));
  await confirmApplied(client, "a");
  expect(toast.dismiss).toHaveBeenCalledWith("config-applied");
  expect(toast.warning).not.toHaveBeenCalled();
  expect(invalidatedTenant()).toBe(false);
});
