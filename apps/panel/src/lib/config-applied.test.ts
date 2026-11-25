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

import { confirmApplied, POLL_ATTEMPTS, summarize } from "@/lib/config-applied";

type P = { service: string; revision: number };
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

beforeEach(() => {
  vi.useFakeTimers();
  for (const fn of Object.values(toast)) fn.mockReset();
  get.mockReset();
});
afterEach(() => vi.useRealTimers());

test("summarize counts processes at or after the target and names services behind", () => {
  const s = summarize(
    state(5, [
      { service: "web", revision: 5 },
      { service: "worker-inbound", revision: 4 },
      { service: "worker-inbound", revision: 3 },
      { service: "web-panel", revision: 6 },
    ]),
    5,
  );
  expect(s).toEqual({ total: 4, applied: 2, behind: ["worker-inbound"] });
});

test("confirms at once when every process already has the revision", async () => {
  get.mockResolvedValue(
    state(5, [
      { service: "web", revision: 5 },
      { service: "worker-inbound", revision: 5 },
    ]),
  );
  await confirmApplied();
  expect(toast.loading).not.toHaveBeenCalled();
  expect(toast.success).toHaveBeenCalledWith("Aplicado en 2 procesos", {
    id: "config-applied",
    duration: 4000,
  });
});

test("shows «Aplicando…» until the laggards catch up, then succeeds", async () => {
  const behind = state(5, [
    { service: "web", revision: 5 },
    { service: "worker-inbound", revision: 4 },
  ]);
  const done = state(5, [
    { service: "web", revision: 5 },
    { service: "worker-inbound", revision: 5 },
  ]);
  get.mockResolvedValueOnce(behind).mockResolvedValueOnce(behind);
  get.mockResolvedValue(done);
  const finished = confirmApplied();
  await vi.advanceTimersByTimeAsync(2000);
  await finished;
  expect(toast.loading).toHaveBeenCalledWith("Aplicando el cambio…", {
    id: "config-applied",
  });
  expect(toast.success).toHaveBeenCalledTimes(1);
  expect(toast.warning).not.toHaveBeenCalled();
});

test("warns with the services still behind after ~10 s", async () => {
  get.mockResolvedValue(
    state(5, [
      { service: "web", revision: 5 },
      { service: "worker-inbound", revision: 4 },
      { service: "worker-outbound", revision: 4 },
    ]),
  );
  const finished = confirmApplied();
  await vi.advanceTimersByTimeAsync(11_000);
  await finished;
  expect(toast.warning).toHaveBeenCalledWith(
    "Aplicado en 1 de 3; siguen con la versión anterior: worker-inbound, worker-outbound",
    { id: "config-applied", duration: 15000 },
  );
  expect(toast.success).not.toHaveBeenCalled();
  expect(get).toHaveBeenCalledTimes(POLL_ATTEMPTS + 1);
});

test("a newer save supersedes the one still polling", async () => {
  const behind = state(5, [{ service: "web", revision: 4 }]);
  get.mockResolvedValue(behind);
  const first = confirmApplied();
  await vi.advanceTimersByTimeAsync(600);
  get.mockResolvedValue(state(6, [{ service: "web", revision: 6 }]));
  const second = confirmApplied();
  await vi.advanceTimersByTimeAsync(11_000);
  await Promise.all([first, second]);
  expect(toast.warning).not.toHaveBeenCalled();
  expect(toast.success).toHaveBeenCalledTimes(1);
});

test("shows nothing when no process reports, and drops the toast on errors", async () => {
  get.mockResolvedValue(state(5, []));
  await confirmApplied();
  expect(toast.dismiss).toHaveBeenCalledWith("config-applied");
  expect(toast.success).not.toHaveBeenCalled();
  toast.dismiss.mockReset();
  get.mockRejectedValue(new Error("down"));
  await confirmApplied();
  expect(toast.dismiss).toHaveBeenCalledWith("config-applied");
  expect(toast.warning).not.toHaveBeenCalled();
});
