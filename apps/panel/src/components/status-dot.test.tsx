import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { StatusDot } from "./status-dot";

test("renders the label and a colored dot", () => {
  render(<StatusDot level="critical" label="Con problemas" />);
  expect(screen.getByText("Con problemas")).toBeInTheDocument();
});

test("renders without a label", () => {
  render(<StatusDot level="ok" />);
  expect(screen.queryByText(/./)).not.toBeInTheDocument();
});
