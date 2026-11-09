import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { ChannelSection } from "./channel-section";
import { OwnerSection } from "./owner-section";

afterEach(() => vi.unstubAllGlobals());

const detail = {
  slug: "demo",
  channel_type: "telegram",
  webhook_url: "https://example.test/webhook",
  public_link: null,
  owner_linked: false,
} as unknown as components["schemas"]["TenantDetail"];

function setup(
  ui: React.ReactNode,
  answer: (url: URL, method: string) => unknown,
) {
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    return new Response(JSON.stringify(answer(new URL(req.url), req.method)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <form>{ui}</form>
    </QueryClientProvider>,
  );
  return { fetcher, client };
}

const secrets = {
  channel_type: "telegram",
  readable: true,
  updated_at: null,
  updated_by: null,
  fields: [],
};

test.each([
  [true, "Registrado"],
  [false, "Sin registrar"],
  [null, "Sin comprobar"],
])("webhook status %s shows %s", async (registered, label) => {
  setup(<ChannelSection detail={detail} />, (url) =>
    url.pathname.endsWith("/telegram-webhook") ? { registered } : secrets,
  );
  expect(await screen.findByText(label)).toBeInTheDocument();
});

test("registering the webhook refreshes its status", async () => {
  const user = userEvent.setup();
  let registered = false;
  const { fetcher } = setup(
    <ChannelSection detail={detail} />,
    (url, method) => {
      if (url.pathname.endsWith("/telegram-webhook")) {
        if (method === "POST") {
          registered = true;
          return { url: "https://example.test/webhook" };
        }
        return { registered };
      }
      return secrets;
    },
  );
  await screen.findByText("Sin registrar");
  const button = screen.getByRole("button", { name: "Registrar webhook" });
  expect(button).toHaveAttribute("type", "button");
  await user.click(button);
  await screen.findByText("Registrado");
  expect(
    fetcher.mock.calls.filter(
      ([r]) =>
        (r as Request).method === "GET" &&
        String((r as Request).url).endsWith("/telegram-webhook"),
    ).length,
  ).toBe(2);
});

test("the webhook status is not requested for other channels", async () => {
  const { fetcher } = setup(
    <ChannelSection detail={{ ...detail, channel_type: "whatsapp" }} />,
    () => ({ ...secrets, channel_type: "whatsapp" }),
  );
  await screen.findByText("Credenciales");
  expect(
    fetcher.mock.calls.some(([r]) =>
      String((r as Request).url).endsWith("/telegram-webhook"),
    ),
  ).toBe(false);
});

test.each([
  [true, true],
  [false, false],
])(
  "owner invite shows expiry and replaces_chat=%s",
  async (replaces, warns) => {
    const user = userEvent.setup();
    const { client } = setup(<OwnerSection detail={detail} />, () => ({
      url: "https://t.me/AvisosBot?start=abc",
      expires_at: "2026-11-10T10:30:00Z",
      replaces_chat: replaces,
    }));
    const invite = screen.getByRole("button", { name: "Invitar al dueño" });
    expect(invite).toHaveAttribute("type", "button");
    await user.click(invite);
    await screen.findByText("https://t.me/AvisosBot?start=abc");
    expect(screen.getByText(/Caduca el/)).toBeInTheDocument();
    const warning = screen.queryByText(
      "Ya hay un chat conectado; este enlace lo sustituirá cuando se use.",
    );
    expect(warning !== null).toBe(warns);
    // The link is never kept in the query cache.
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain("start=abc");
  },
);
