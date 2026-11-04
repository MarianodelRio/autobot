import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ConfirmDialog } from "./confirm-dialog";

test("stays disabled until the exact text is typed, then confirms", async () => {
  const onConfirm = vi.fn();
  render(
    <ConfirmDialog
      open={true}
      onOpenChange={vi.fn()}
      title="Dar de baja"
      confirmText="autocares-ss"
      onConfirm={onConfirm}
    />,
  );
  const user = userEvent.setup();
  const confirmButton = screen.getByRole("button", { name: "Confirmar" });
  expect(confirmButton).toBeDisabled();

  const input = screen.getByLabelText(/autocares-ss/);
  await user.type(input, "wrong-slug");
  expect(confirmButton).toBeDisabled();

  await user.clear(input);
  await user.type(input, "autocares-ss");
  expect(confirmButton).toBeEnabled();

  await user.click(confirmButton);
  expect(onConfirm).toHaveBeenCalledOnce();
});

test("without confirmText, the action is enabled right away", () => {
  render(
    <ConfirmDialog
      open={true}
      onOpenChange={vi.fn()}
      title="Pausar"
      onConfirm={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Confirmar" })).toBeEnabled();
});
