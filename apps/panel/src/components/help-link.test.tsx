import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { docsHref, HelpLink } from "./help-link";

describe("HelpLink", () => {
  it("builds /docs/ URLs", () => {
    expect(docsHref("incidencias/")).toBe("/docs/incidencias/");
    expect(docsHref("/procedimientos/panel/#logs")).toBe(
      "/docs/procedimientos/panel/#logs",
    );
  });

  it("is a plain link that opens in a new tab", () => {
    render(<HelpLink page="procedimientos/demo/" />);
    const link = screen.getByRole("link", { name: /ayuda/i });
    expect(link.getAttribute("href")).toBe("/docs/procedimientos/demo/");
    expect(link.getAttribute("target")).toBe("_blank");
  });
});
