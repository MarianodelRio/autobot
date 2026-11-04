import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { CodeEditor } from "./code-editor";

vi.mock("@uiw/react-codemirror", () => ({
  default: ({
    value,
    onChange,
    onKeyDown,
  }: {
    value: string;
    onChange?: (value: string) => void;
    onKeyDown?: (event: React.KeyboardEvent) => void;
  }) => (
    <textarea
      aria-label="sql"
      value={value}
      onChange={(event) => onChange?.(event.target.value)}
      onKeyDown={onKeyDown}
    />
  ),
}));

test("runs on Ctrl/Cmd+Enter but not on a plain Enter", async () => {
  const onRun = vi.fn();
  render(<CodeEditor value="SELECT 1" language="sql" onRun={onRun} />);
  const editor = await screen.findByLabelText("sql");

  editor.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
  );
  expect(onRun).not.toHaveBeenCalled();

  editor.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "Enter",
      metaKey: true,
      bubbles: true,
    }),
  );
  expect(onRun).toHaveBeenCalledTimes(1);

  editor.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "Enter",
      ctrlKey: true,
      bubbles: true,
    }),
  );
  expect(onRun).toHaveBeenCalledTimes(2);
});
