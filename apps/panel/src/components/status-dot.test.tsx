import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import {
  STATUS_DOT_COLOR,
  STATUS_DOT_LEVELS,
  StatusDot,
  toStatusDotLevel,
} from "./status-dot";

function dotOf(container: HTMLElement) {
  return container.querySelector("span[aria-hidden='true']");
}

describe("StatusDot", () => {
  test.each(STATUS_DOT_LEVELS)("level %s uses its own color class", (level) => {
    const { container } = render(<StatusDot level={level} label="x" />);
    expect(dotOf(container)).toHaveClass(STATUS_DOT_COLOR[level]);
  });

  test("every level has a distinct color", () => {
    const colors = STATUS_DOT_LEVELS.map((level) => STATUS_DOT_COLOR[level]);
    expect(new Set(colors).size).toBe(STATUS_DOT_LEVELS.length);
  });

  test("the dot is decorative; the label carries the meaning", () => {
    const { container } = render(
      <StatusDot level="critical" label="Fallando" />,
    );
    expect(dotOf(container)).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Fallando")).toBeVisible();
  });

  test("without a label only the dot renders", () => {
    const { container } = render(<StatusDot level="ok" />);
    expect(container.textContent).toBe("");
    expect(dotOf(container)).toBeInTheDocument();
  });
});

describe("toStatusDotLevel", () => {
  test("keeps known levels and maps anything else to unknown", () => {
    expect(toStatusDotLevel("warning")).toBe("warning");
    expect(toStatusDotLevel("fatal")).toBe("unknown");
    expect(toStatusDotLevel("")).toBe("unknown");
  });
});
