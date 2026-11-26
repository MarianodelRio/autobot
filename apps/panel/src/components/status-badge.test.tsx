import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { StatusBadge } from "./status-badge";

test("knows the info severity", () => {
  render(<StatusBadge status="info" />);
  expect(screen.getByText("Info")).toBeInTheDocument();
});

test("an unknown value reads «Desconocido» instead of breaking the screen", () => {
  render(<StatusBadge status="whatever" />);
  expect(screen.getByText("Desconocido")).toBeInTheDocument();
});
