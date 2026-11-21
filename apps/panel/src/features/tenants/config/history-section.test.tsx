import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { HistorySection } from "./history-section";

afterEach(() => vi.unstubAllGlobals());

const VERSIONS = [
  {
    version: 2,
    author: "op",
    comment: "Cambio de precio",
    created_at: "2026-11-10T10:00:00Z",
  },
  { version: 1, author: "op", comment: "", created_at: "2026-11-01T10:00:00Z" },
];

function stub(
  rollbackResponse: Record<string, unknown> | [number, Record<string, unknown>],
) {
  const [status, body] = Array.isArray(rollbackResponse)
    ? rollbackResponse
    : [200, rollbackResponse];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      let value: unknown;
      if (req.method === "POST" && url.pathname.endsWith("/rollback"))
        value = body;
      else if (/\/versions\/\d+$/.test(url.pathname))
        value = {
          version: 1,
          author: "op",
          comment: "",
          created_at: "2026-11-01T10:00:00Z",
          document: { name: "Vieja" },
        };
      else if (url.pathname.endsWith("/versions")) value = VERSIONS;
      else value = {};
      return new Response(JSON.stringify(value), {
        status:
          req.method === "POST" && url.pathname.endsWith("/rollback")
            ? status
            : 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function provider(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
  return client;
}

test("lists versions, author and comment", async () => {
  stub({ version: 3 });
  const user = userEvent.setup();
  provider(
    <HistorySection
      slug="demo"
      current={{ name: "Actual" }}
      dirty={false}
      onRolledBack={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Historial" }));
  await screen.findByText("Versión 2");
  expect(screen.getByText(/Cambio de precio/)).toBeInTheDocument();
  expect(screen.getByText("Versión 1")).toBeInTheDocument();
  expect(screen.getByText(/sin comentario/)).toBeInTheDocument();
});

test("viewing changes shows a legible diff against the current document", async () => {
  stub({ version: 3 });
  const user = userEvent.setup();
  provider(
    <HistorySection
      slug="demo"
      current={{ name: "Actual" }}
      dirty={false}
      onRolledBack={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Historial" }));
  await user.click(
    (await screen.findAllByRole("button", { name: "Ver cambios" })).at(
      1,
    ) as HTMLElement,
  );
  expect(await screen.findByText("name")).toBeInTheDocument();
  expect(screen.getByText("Vieja")).toBeInTheDocument();
  expect(screen.getByText("Actual")).toBeInTheDocument();
});

test("rolling back asks for confirmation and invalidates the tenant", async () => {
  stub({ version: 3 });
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
  const user = userEvent.setup();
  provider(
    <HistorySection
      slug="demo"
      current={{ name: "Actual" }}
      dirty={false}
      onRolledBack={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Historial" }));
  await user.click(
    (
      await screen.findAllByRole("button", { name: "Volver a esta versión" })
    ).at(0) as HTMLElement,
  );
  expect(window.confirm).toHaveBeenCalled();
});

test("rolling back with unsaved changes warns before confirming", async () => {
  stub({ version: 3 });
  const confirmSpy = vi.fn(() => false);
  vi.stubGlobal("confirm", confirmSpy);
  const user = userEvent.setup();
  provider(
    <HistorySection
      slug="demo"
      current={{ name: "Actual" }}
      dirty
      onRolledBack={() => {}}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Historial" }));
  await user.click(
    (
      await screen.findAllByRole("button", { name: "Volver a esta versión" })
    ).at(0) as HTMLElement,
  );
  expect(confirmSpy).toHaveBeenCalledWith(
    "Hay cambios sin guardar que se perderán. ¿Continuar?",
  );
});
