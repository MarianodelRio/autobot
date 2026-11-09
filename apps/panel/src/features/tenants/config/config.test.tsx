import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { ConfigEditor, errorsToSchema } from "./editor";
import { SecretsForm } from "./secrets-form";
import { StatusAction } from "./status-action";

const detail: components["schemas"]["TenantDetail"] = {
  slug: "test",
  name: "Original",
  pack: "bus",
  status: "active",
  timezone: "Europe/Madrid",
  document: { name: "Original", config: { price: 1 } },
  version: 1,
  degraded: [],
  ambiguous: false,
  main_disabled: [],
  health: "ok",
  health_reasons: [],
  health_checked_at: null,
  open_alerts: [],
  channel_type: null,
  webhook_url: null,
  public_link: null,
  owner_linked: false,
  month: { inbound: 0, outbound: 0, users: 0, cost_eur: "0" },
};
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
const schema = {
  document: {
    type: "object",
    properties: {
      name: { type: "string", title: "Nombre" },
      config: {
        type: "object",
        properties: { price: { type: "number", title: "Precio" } },
      },
    },
  },
  ui_schema: { read_only: [], widgets: {}, groups: [] },
};
afterEach(() => vi.unstubAllGlobals());
test("maps validation paths to field errors", () => {
  expect(
    errorsToSchema(["config.price: valor no válido", "name: falta"]),
  ).toEqual({
    config: { price: { __errors: ["valor no válido"] } },
    name: { __errors: ["falta"] },
  });
});
test("editor synchronizes YAML, shows diff and applies 422 errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) =>
      req.method === "PUT"
        ? json(
            {
              code: "validation_error",
              message: "No válido",
              details: ["name: nombre no válido"],
            },
            422,
          )
        : json(schema),
    ),
  );
  const changed = vi.fn();
  provider(<ConfigEditor detail={detail} onDirtyChange={changed} />);
  const user = userEvent.setup();
  const name = await screen.findByLabelText("Nombre");
  await user.clear(name);
  await user.type(name, "Nuevo");
  await user.click(screen.getByRole("button", { name: "Editar YAML" }));
  expect(
    (screen.getByLabelText("Documento YAML") as HTMLTextAreaElement).value,
  ).toContain("Nuevo");
  fireEvent.change(screen.getByLabelText("Documento YAML"), {
    target: { value: "name: Desde YAML\nconfig:\n  price: 2\n" },
  });
  await user.click(
    screen.getByRole("button", { name: "Volver al formulario" }),
  );
  expect(screen.getByLabelText("Nombre")).toHaveValue("Desde YAML");
  await user.click(screen.getByRole("button", { name: "Editar YAML" }));
  await user.click(screen.getByRole("button", { name: "Ver cambios" }));
  expect(screen.getByText(/Original/)).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await user.type(screen.getByLabelText("Comentario (opcional)"), "Cambio");
  await user.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByText("name: nombre no válido")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Volver al formulario" }),
  );
  expect(screen.getAllByText("nombre no válido").length).toBeGreaterThan(0);
  expect(changed).toHaveBeenCalledWith(true);
});
test("conflict offers differences and reload", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) =>
      req.method === "PUT"
        ? json({ code: "conflict", message: "Conflicto", details: [] }, 409)
        : req.url.includes("/packs/")
          ? json(schema)
          : json({
              ...detail,
              document: { name: "Remoto", config: { price: 1 } },
              version: 2,
            }),
    ),
  );
  provider(<ConfigEditor detail={detail} onDirtyChange={vi.fn()} />);
  const user = userEvent.setup();
  const name = await screen.findByLabelText("Nombre");
  await user.clear(name);
  await user.type(name, "Local");
  await user.type(screen.getByLabelText("Comentario (opcional)"), "Cambio");
  await user.click(screen.getByRole("button", { name: "Guardar" }));
  await screen.findByText("Hay una versión más reciente.");
  await user.click(screen.getByRole("button", { name: "Ver diferencias" }));
  await screen.findByText(/Remoto/);
  await user.click(screen.getByRole("button", { name: "Recargar" }));
  await waitFor(() =>
    expect(screen.getByLabelText("Nombre")).toHaveValue("Remoto"),
  );
});
test("activation requires unblocked checklist and exact slug", async () => {
  let blocked = true;
  const fetcher = vi.fn(async (req: Request) =>
    req.method === "POST"
      ? json({ version: 2 })
      : json([
          {
            key: "channel",
            label: "Canal",
            ok: !blocked,
            blocking: true,
            detail: "Revisar",
          },
        ]),
  );
  vi.stubGlobal("fetch", fetcher);
  provider(<StatusAction slug="test" status="onboarding" />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Activar" }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText(/bloqueante/);
  await user.type(within(dialog).getByLabelText("Escribe test"), "test");
  expect(
    within(dialog).getByRole("button", { name: "Activar" }),
  ).toBeDisabled();
  await user.keyboard("{Escape}");
  blocked = false;
  await user.click(screen.getByRole("button", { name: "Activar" }));
  const reopened = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(within(reopened).queryByText(/bloqueante/)).not.toBeInTheDocument(),
  );
  expect(
    within(reopened).getByRole("button", { name: "Activar" }),
  ).toBeDisabled();
  await user.type(within(reopened).getByLabelText("Escribe test"), "test");
  await user.click(within(reopened).getByRole("button", { name: "Activar" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([request]) => request.method === "POST"),
    ).toBe(true),
  );
});
const accessTokenField = {
  name: "access_token",
  set: true,
  label: "Token de acceso",
  help: "Token permanente del System User",
  generatable: false,
};

test("secret form shows an error on failure without caching the typed value", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({ code: "bad_request", message: "error", details: [] }, 400),
    ),
  );
  const client = provider(
    <SecretsForm slug="test" fields={[accessTokenField]} />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "Cambiar credenciales" }),
  );
  const input = screen.getByLabelText("Token de acceso");
  await user.type(input, "test-secret");
  await user.click(screen.getByRole("button", { name: "Guardar secretos" }));
  await screen.findByRole("alert");
  expect(JSON.stringify(client.getQueryCache().getAll())).not.toContain(
    "test-secret",
  );
  expect(client.getMutationCache().getAll()).toHaveLength(0);
});

test("partial replacement omits blank fields and a generated value fills its field", async () => {
  let sent: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      sent = await request.json();
      return new Response(null, { status: 204 });
    }),
  );
  provider(
    <SecretsForm
      slug="test"
      fields={[
        accessTokenField,
        {
          name: "verify_token",
          set: true,
          label: "Token de verificación",
          help: "Se pega también en el webhook de Meta",
          generatable: true,
        },
      ]}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "Cambiar credenciales" }),
  );
  await user.type(screen.getByLabelText("Token de acceso"), "secret-one");
  await user.click(screen.getByRole("button", { name: "Generar" }));
  await user.click(screen.getByRole("button", { name: "Guardar secretos" }));
  await waitFor(() => expect(sent).toBeDefined());
  const body = sent as { secrets: Record<string, string> };
  expect(body.secrets.access_token).toBe("secret-one");
  expect(body.secrets.verify_token).toHaveLength(48);
});
