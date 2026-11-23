import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { NotificationsTab } from "./notifications-tab";

afterEach(() => vi.unstubAllGlobals());

const notice = (text: string) => ({
  kind: "booking",
  text,
  status: "sent",
  created_at: "2026-11-04T10:00:00Z",
  sent_at: null,
});

test("loads further notifications with the cursor of the previous page", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url);
      urls.push(url.search);
      const body = url.searchParams.get("cursor")
        ? { items: [notice("Aviso viejo")], next_cursor: null }
        : { items: [notice("Aviso nuevo")], next_cursor: "abc" };
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NotificationsTab slug="demo" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Aviso nuevo")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cargar más" }));
  expect(await screen.findByText("Aviso viejo")).toBeInTheDocument();
  expect(screen.getByText("Aviso nuevo")).toBeInTheDocument();
  expect(urls[1]).toContain("cursor=abc");
  expect(screen.queryByRole("button", { name: "Cargar más" })).toBeNull();
});
