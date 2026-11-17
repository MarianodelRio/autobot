import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { JsonDiff } from "./json-diff";

test("no changes", () => {
  render(<JsonDiff before={{ name: "A" }} after={{ name: "A" }} />);
  expect(screen.getByText("Sin cambios.")).toBeInTheDocument();
});

test("a changed scalar field shows its path and both values", () => {
  render(<JsonDiff before={{ name: "A" }} after={{ name: "B" }} />);
  expect(screen.getByText("name")).toBeInTheDocument();
  expect(screen.getByText("A")).toBeInTheDocument();
  expect(screen.getByText("B")).toBeInTheDocument();
});

test("a nested field uses its dotted path", () => {
  render(
    <JsonDiff
      before={{ config: { price: 1 } }}
      after={{ config: { price: 2 } }}
    />,
  );
  expect(screen.getByText("config.price")).toBeInTheDocument();
});

test("an added field has no before value", () => {
  render(<JsonDiff before={{}} after={{ name: "A" }} />);
  expect(screen.getByText("name")).toBeInTheDocument();
  expect(screen.queryByText("—")).not.toBeInTheDocument();
  expect(screen.getByText("A")).toBeInTheDocument();
});

test("a removed field has no after value", () => {
  render(<JsonDiff before={{ name: "A" }} after={{}} />);
  expect(screen.getByText("A")).toBeInTheDocument();
});

test("an array value that changed is compared as a whole, not element by element", () => {
  render(
    <JsonDiff
      before={{ opening_hours: { lunes: ["09:00-13:00"] } }}
      after={{ opening_hours: { lunes: ["09:00-14:00"] } }}
    />,
  );
  expect(screen.getByText("opening_hours.lunes")).toBeInTheDocument();
  expect(screen.getByText('["09:00-13:00"]')).toBeInTheDocument();
  expect(screen.getByText('["09:00-14:00"]')).toBeInTheDocument();
});
