import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { LoginPage } from "./login-page";

function renderLoginPage(onSuccess = vi.fn()) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <LoginPage onSuccess={onSuccess} />
    </QueryClientProvider>,
  );
  return { onSuccess };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("rejects an otp that is not 6 digits", async () => {
  renderLoginPage();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Usuario"), "operator");
  await user.type(screen.getByLabelText("Contraseña"), "secret");
  await user.type(screen.getByLabelText("Código"), "123");
  await user.click(screen.getByRole("button", { name: "Entrar" }));

  expect(
    await screen.findByText("El código tiene 6 dígitos."),
  ).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("requires a username and a password", async () => {
  renderLoginPage();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Entrar" }));

  expect(await screen.findByText("Falta el usuario.")).toBeInTheDocument();
  expect(screen.getByText("Falta la contraseña.")).toBeInTheDocument();
});

test("shows the backend's generic error on failure, not a success", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Credenciales no válidas." }), {
          status: 401,
        }),
    ),
  );
  const { onSuccess } = renderLoginPage();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Usuario"), "operator");
  await user.type(screen.getByLabelText("Contraseña"), "wrong");
  await user.type(screen.getByLabelText("Código"), "123456");
  await user.click(screen.getByRole("button", { name: "Entrar" }));

  await waitFor(() => {
    expect(screen.getByText("Credenciales no válidas.")).toBeInTheDocument();
  });
  expect(onSuccess).not.toHaveBeenCalled();
});

test("calls onSuccess once the API accepts the login", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ username: "operator" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  const { onSuccess } = renderLoginPage();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Usuario"), "operator");
  await user.type(screen.getByLabelText("Contraseña"), "secret");
  await user.type(screen.getByLabelText("Código"), "123456");
  await user.click(screen.getByRole("button", { name: "Entrar" }));

  await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
});
