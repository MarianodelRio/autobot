import type { WidgetProps } from "@rjsf/utils";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { TimezoneWidget } from "./timezone-widget";

function props(value: string, onChange: (value: string) => void): WidgetProps {
  return {
    id: "root_timezone",
    value,
    onChange,
  } as unknown as WidgetProps;
}

test("lists IANA zones and lets the operator pick one", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<TimezoneWidget {...props("Europe/Madrid", onChange)} />);
  const select = screen.getByRole("combobox");
  expect(select).toHaveValue("Europe/Madrid");
  await user.selectOptions(select, "Europe/Lisbon");
  expect(onChange).toHaveBeenCalledWith("Europe/Lisbon");
});

test("keeps an unknown stored value selectable instead of silently dropping it", () => {
  const onChange = vi.fn();
  render(<TimezoneWidget {...props("Not/AZone", onChange)} />);
  expect(screen.getByRole("combobox")).toHaveValue("Not/AZone");
});
