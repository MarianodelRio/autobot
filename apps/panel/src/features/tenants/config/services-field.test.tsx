import type { FieldProps } from "@rjsf/utils";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ServicesField } from "./services-field";

type Service = {
  name: string;
  price_eur?: number | null;
  duration_min: number;
  client_presence_min: number;
};

function props(
  formData: Record<string, Service>,
  onChange: (value: Record<string, Service>) => void,
): FieldProps<Record<string, Service>> {
  return {
    schema: { title: "Servicios", description: "Hasta 9." },
    formData,
    onChange,
    fieldPathId: { path: [] },
  } as unknown as FieldProps<Record<string, Service>>;
}

test("adding a service assigns the next free numeric id automatically", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <ServicesField
      {...props(
        { "1": { name: "Corte", duration_min: 30, client_presence_min: 30 } },
        onChange,
      )}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Añadir servicio" }));
  expect(onChange).toHaveBeenCalledWith(
    {
      "1": { name: "Corte", duration_min: 30, client_presence_min: 30 },
      "2": { name: "", duration_min: 30, client_presence_min: 30 },
    },
    [],
  );
});

test("adding a service fills a gap left by a removed one", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <ServicesField
      {...props(
        { "2": { name: "Tinte", duration_min: 60, client_presence_min: 90 } },
        onChange,
      )}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Añadir servicio" }));
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({
      "1": { name: "", duration_min: 30, client_presence_min: 30 },
    }),
    [],
  );
});

test("removing a service deletes only its own row", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <ServicesField
      {...props(
        {
          "1": { name: "Corte", duration_min: 30, client_presence_min: 30 },
          "2": { name: "Tinte", duration_min: 60, client_presence_min: 90 },
        },
        onChange,
      )}
    />,
  );
  await user.click(
    screen.getAllByRole("button", { name: "Eliminar" }).at(0) as HTMLElement,
  );
  expect(onChange).toHaveBeenCalledWith(
    { "2": { name: "Tinte", duration_min: 60, client_presence_min: 90 } },
    [],
  );
});

test("adding a service is disabled once there are 9", () => {
  const onChange = vi.fn();
  const nine = Object.fromEntries(
    Array.from({ length: 9 }, (_, i) => [
      String(i + 1),
      { name: `s${i}`, duration_min: 30, client_presence_min: 30 },
    ]),
  );
  render(<ServicesField {...props(nine, onChange)} />);
  expect(
    screen.getByRole("button", { name: "Añadir servicio" }),
  ).toBeDisabled();
});

test("editing the price clears to null, not NaN, when the input is emptied", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <ServicesField
      {...props(
        {
          "1": {
            name: "Corte",
            price_eur: 10,
            duration_min: 30,
            client_presence_min: 30,
          },
        },
        onChange,
      )}
    />,
  );
  const price = screen.getByDisplayValue("10");
  await user.clear(price);
  expect(onChange).toHaveBeenLastCalledWith(
    {
      "1": {
        name: "Corte",
        price_eur: null,
        duration_min: 30,
        client_presence_min: 30,
      },
    },
    [],
  );
});
