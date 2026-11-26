import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { renderWithRouter } from "@/lib/test-router";
import { AppLink, isPanelPath } from "./app-link";

test("tells panel screens from the docs site and external pages", () => {
  expect(isPanelPath("/clientes/demo?tab=contactos")).toBe(true);
  expect(isPanelPath("/incidencias")).toBe(true);
  expect(isPanelPath("/docs/incidencias/")).toBe(false);
  expect(isPanelPath("/api/panel/me")).toBe(false);
  expect(isPanelPath("//evil.example")).toBe(false);
  expect(isPanelPath("https://github.com/x")).toBe(false);
});

test("a panel path navigates with the router, without a page load", async () => {
  const router = await renderWithRouter(
    <AppLink href="/clientes/demo?tab=contactos">Ver cliente</AppLink>,
  );
  const link = screen.getByRole("link", { name: "Ver cliente" });
  expect(link).toHaveAttribute("href", "/clientes/demo?tab=contactos");
  // The router handled it: the click was prevented (no full reload) and the
  // in-memory history moved to the target, query string included.
  const click = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
  });
  link.dispatchEvent(click);
  expect(click.defaultPrevented).toBe(true);
  expect(router.history.location.pathname).toBe("/clientes/demo");
  expect(router.history.location.search).toBe("?tab=contactos");
});

test("Ctrl+clic and external links are left to the browser", async () => {
  const router = await renderWithRouter(
    <>
      <AppLink href="/clientes/demo">Panel</AppLink>
      <AppLink href="/docs/incidencias/">Docs</AppLink>
    </>,
  );
  const ctrl = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ctrlKey: true,
  });
  screen.getByRole("link", { name: "Panel" }).dispatchEvent(ctrl);
  expect(ctrl.defaultPrevented).toBe(false);
  const docs = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
  });
  screen.getByRole("link", { name: "Docs" }).dispatchEvent(docs);
  expect(docs.defaultPrevented).toBe(false);
  expect(router.history.location.pathname).toBe("/");
});

test("keyboard activation also navigates in place", async () => {
  const user = userEvent.setup();
  const router = await renderWithRouter(
    <AppLink href="/sistema">Sistema</AppLink>,
  );
  screen.getByRole("link", { name: "Sistema" }).focus();
  await user.keyboard("{Enter}");
  expect(router.history.location.pathname).toBe("/sistema");
});
