import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { requestReauth } from "@/lib/reauth";
import { ReauthDialog } from "./reauth-dialog";

function json(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  document.cookie = "autobot_panel_csrftoken=tok";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a valid code calls step-up and resolves the request", async () => {
  const fetchMock = vi.fn(async () => json({ ok: true }, 200));
  vi.stubGlobal("fetch", fetchMock);
  render(<ReauthDialog />);
  const result = requestReauth();
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Código TOTP"), "123456");
  await user.click(screen.getByRole("button", { name: "Confirmar" }));
  await expect(result).resolves.toBe(true);
  const sent = (fetchMock.mock.calls[0] as unknown as [Request])[0];
  expect(sent.url).toContain("/auth/step-up");
  expect(await sent.json()).toEqual({ otp: "123456" });
});

test("a rejected code shows the error and keeps the dialog open", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json(
        { code: "invalid_otp", message: "Código no válido.", details: [] },
        403,
      ),
    ),
  );
  render(<ReauthDialog />);
  let settled = false;
  requestReauth().then(() => {
    settled = true;
  });
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Código TOTP"), "000000");
  await user.click(screen.getByRole("button", { name: "Confirmar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Código no válido.",
  );
  expect(settled).toBe(false);
  await user.click(screen.getByRole("button", { name: "Cancelar" }));
  await waitFor(() => expect(settled).toBe(true));
});

test("cancelling resolves false", async () => {
  render(<ReauthDialog />);
  const result = requestReauth();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Cancelar" }));
  await expect(result).resolves.toBe(false);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
