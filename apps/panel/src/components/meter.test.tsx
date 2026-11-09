import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Meter } from "./meter";

test("renders the value and the meter role", () => {
  render(<Meter label="CPU" value={18} />);
  const meter = screen.getByRole("meter", { name: "CPU" });
  expect(meter).toHaveAttribute("aria-valuenow", "18");
  expect(screen.getByText("18 %")).toBeInTheDocument();
});

test("renders a dash and no fill when value is null", () => {
  render(<Meter label="RAM" value={null} />);
  const meter = screen.getByRole("meter", { name: "RAM" });
  expect(meter).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByText("—")).toBeInTheDocument();
});
