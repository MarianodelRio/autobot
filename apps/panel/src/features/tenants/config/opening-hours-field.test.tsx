import type { FieldProps } from "@rjsf/utils";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { OpeningHoursField } from "./opening-hours-field";

function props(
  formData: Record<string, string[]>,
  onChange: (value: Record<string, string[]>) => void,
): FieldProps<Record<string, string[]>> {
  return {
    schema: { title: "Horario de apertura" },
    formData,
    onChange,
    fieldPathId: { path: [] },
  } as unknown as FieldProps<Record<string, string[]>>;
}

test("a closed day has no time inputs, and opening it adds a default range", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<OpeningHoursField {...props({}, onChange)} />);
  expect(screen.getAllByText("Cerrado")).toHaveLength(7);

  await user.click(screen.getByRole("checkbox", { name: "Lunes" }));
  expect(onChange).toHaveBeenCalledWith({ lunes: ["09:00-18:00"] }, []);
});

test("closing an open day removes its key entirely, never an empty array", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <OpeningHoursField {...props({ lunes: ["09:00-13:00"] }, onChange)} />,
  );

  await user.click(screen.getByRole("checkbox", { name: "Lunes" }));
  expect(onChange).toHaveBeenCalledWith({}, []);
});

test("adding a second range for a day appends to its list", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <OpeningHoursField {...props({ martes: ["09:00-13:00"] }, onChange)} />,
  );

  await user.click(screen.getByRole("button", { name: "+ Añadir tramo" }));
  expect(onChange).toHaveBeenCalledWith(
    { martes: ["09:00-13:00", "09:00-18:00"] },
    [],
  );
});

test("removing the only range for a day closes it instead of leaving []", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <OpeningHoursField {...props({ jueves: ["09:00-13:00"] }, onChange)} />,
  );

  await user.click(
    screen.getByRole("button", { name: "Quitar tramo de jueves" }),
  );
  expect(onChange).toHaveBeenCalledWith({}, []);
});

test("field-level errors are shown", () => {
  const onChange = vi.fn();
  render(
    <OpeningHoursField
      {...props({}, onChange)}
      errorSchema={{ __errors: ["falta al menos un día"] } as never}
    />,
  );
  expect(screen.getByText("falta al menos un día")).toBeInTheDocument();
});
