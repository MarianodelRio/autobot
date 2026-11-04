import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { History } from "./history";

afterEach(() => vi.unstubAllGlobals());
test("compares adjacent versions and restores with comment", async () => {
  let body: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const url = new URL(request.url);
      let value: unknown;
      if (request.method === "POST") {
        body = await request.json();
        value = { version: 3 };
      } else if (url.pathname.endsWith("/versions"))
        value = [
          {
            version: 2,
            author: "op",
            comment: "segunda",
            created_at: "2026-11-04T10:00:00Z",
          },
          {
            version: 1,
            author: "op",
            comment: "primera",
            created_at: "2026-11-03T10:00:00Z",
          },
        ];
      else {
        const version = Number(url.pathname.split("/").pop());
        value = {
          version,
          author: "op",
          comment: "",
          created_at: "2026-11-04T10:00:00Z",
          document: { name: version === 2 ? "Nuevo" : "Anterior" },
        };
      }
      return new Response(JSON.stringify(value), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <History slug="test" />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Versión 2" }));
  await screen.findByText(/Anterior/);
  expect(
    screen.getByRole("button", { name: "Volver a esta versión" }),
  ).toBeDisabled();
  await user.type(screen.getByLabelText("Comentario obligatorio"), "Restaurar");
  await user.click(
    screen.getByRole("button", { name: "Volver a esta versión" }),
  );
  await waitFor(() =>
    expect(body).toEqual({ version: 2, comment: "Restaurar" }),
  );
});
