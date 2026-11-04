import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("renders the placeholder page", () => {
  render(<App />);
  expect(screen.getByText("Autobot")).toBeInTheDocument();
});
