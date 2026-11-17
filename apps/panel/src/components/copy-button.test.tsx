import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, expect, test, vi } from "vitest";
import { CopyButton } from "./copy-button";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.restoreAllMocks());

test("copies the value and confirms it", async () => {
  const user = userEvent.setup();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  render(<CopyButton value="hola" />);
  await user.click(screen.getByRole("button", { name: "Copiar" }));
  expect(writeText).toHaveBeenCalledWith("hola");
  expect(toast.success).toHaveBeenCalledWith("Copiado.");
});
