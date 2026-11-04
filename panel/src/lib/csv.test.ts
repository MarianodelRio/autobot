import { expect, test } from "vitest";
import { toDelimited } from "./csv";

test("quotes fields with commas, quotes or newlines for CSV", () => {
  const csv = toDelimited(
    ["name", "note"],
    [
      ["Ana, S.L.", 'dice "hola"'],
      ["Bea", "línea 1\nlínea 2"],
    ],
    ",",
  );
  expect(csv).toBe(
    'name,note\r\n"Ana, S.L.","dice ""hola"""\r\nBea,"línea 1\nlínea 2"',
  );
});

test("quotes fields with tabs for TSV but leaves plain commas alone", () => {
  const tsv = toDelimited(["a", "b"], [["uno\tdos", "tres, cuatro"]], "\t");
  expect(tsv).toBe('a\tb\r\n"uno\tdos"\ttres, cuatro');
});

test("renders null as empty and stringifies non-string values", () => {
  const csv = toDelimited(["n"], [[null], [42], [true]], ",");
  expect(csv).toBe("n\r\n\r\n42\r\ntrue");
});
