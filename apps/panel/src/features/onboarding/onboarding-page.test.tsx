import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OnboardingPage, slugFromName, validSlug } from "./onboarding-page";

function provider(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
  return client;
}
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
const packs = [{ name: "bus", has_template: true, has_datasets: true }];
const schema = {
  document: {
    type: "object",
    properties: {
      config: {
        type: "object",
        properties: { price: { type: "number", title: "Precio" } },
      },
    },
  },
  ui_schema: { widgets: {} },
};
const template = { config: { price: 1 } };

function router(
  taken: Set<string>,
  onPost?: (body: unknown) => Response,
): (request: Request) => Promise<Response> {
  return async (request: Request) => {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname.endsWith("/tenants"))
      return onPost ? onPost(await request.json()) : json({ version: 1 });
    if (url.pathname.endsWith("/packs")) return json(packs);
    if (url.pathname.endsWith("/tenant-slug-availability"))
      return json({
        available: !taken.has(url.searchParams.get("slug") ?? ""),
      });
    if (url.pathname.endsWith("/schema")) return json(schema);
    if (url.pathname.endsWith("/template")) return json(template);
    return json({}, 404);
  };
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test("slugFromName strips accents and spacing, validSlug enforces the pattern", () => {
  expect(slugFromName("Peluquería Ana")).toBe("peluqueria-ana");
  expect(slugFromName("  Dos   espacios ")).toBe("dos-espacios");
  expect(validSlug("peluqueria-ana")).toBe(true);
  expect(validSlug("Mayus")).toBe(false);
  expect(validSlug("a".repeat(65))).toBe(false);
});

test("derives the slug from the name and reports an existing one", async () => {
  vi.stubGlobal("fetch", vi.fn(router(new Set(["peluqueria-ana"]))));
  provider(<OnboardingPage onCreated={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "bus" }));
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await user.type(screen.getByLabelText("Nombre"), "Peluquería Ana");
  expect(screen.getByLabelText("Slug")).toHaveValue("peluqueria-ana");
  await screen.findByText("Este slug ya existe.");
  expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
});

test("blocks moving on until the basic data is complete and the slug is free", async () => {
  vi.stubGlobal("fetch", vi.fn(router(new Set())));
  provider(<OnboardingPage onCreated={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "bus" }));
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  await user.type(screen.getByLabelText("Nombre"), "Taller Centro");
  await screen.findByText("Slug disponible.");
  expect(screen.getByRole("button", { name: "Siguiente" })).not.toBeDisabled();
  await user.clear(screen.getByLabelText("Zona horaria"));
  expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
});

test("submits the review step as the POST body and creates the tenant", async () => {
  let sent: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      router(new Set(), (body) => {
        sent = body;
        return json({ version: 1 });
      }),
    ),
  );
  const onCreated = vi.fn();
  provider(<OnboardingPage onCreated={onCreated} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "bus" }));
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await user.type(screen.getByLabelText("Nombre"), "Taller Centro");
  await screen.findByText("Slug disponible.");
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByLabelText("Precio");
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByText(/Revisión/);
  await user.click(screen.getByRole("button", { name: "Crear cliente" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("taller-centro"));
  expect(sent).toEqual({
    pack: "bus",
    slug: "taller-centro",
    name: "Taller Centro",
    timezone: "Europe/Madrid",
    channel_type: "whatsapp",
    config: { price: 1 },
    comment: "",
  });
});

test("a 422 on creation returns to the config step with the fields marked", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      router(new Set(), () =>
        json(
          {
            code: "validation_error",
            message: "No válido",
            details: ["config.price: valor no válido"],
          },
          422,
        ),
      ),
    ),
  );
  provider(<OnboardingPage onCreated={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "bus" }));
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await user.type(screen.getByLabelText("Nombre"), "Taller Centro");
  await screen.findByText("Slug disponible.");
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByLabelText("Precio");
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByText(/Revisión/);
  await user.click(screen.getByRole("button", { name: "Crear cliente" }));
  await screen.findByText("valor no válido");
  expect(screen.getByText(/Configuración/)).toBeInTheDocument();
  expect(screen.getByLabelText("Precio")).toBeInTheDocument();
});
