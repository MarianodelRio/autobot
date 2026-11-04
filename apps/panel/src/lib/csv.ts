function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Quotes a field for CSV/TSV when it contains the delimiter, a quote or a newline. */
function quoteIfNeeded(value: string, delimiter: string): string {
  if (
    !value.includes(delimiter) &&
    !value.includes('"') &&
    !/[\r\n]/.test(value)
  )
    return value;
  return `"${value.replace(/"/g, '""')}"`;
}

export function toDelimited(
  columns: string[],
  rows: unknown[][],
  delimiter: "," | "\t",
): string {
  const lines = [columns, ...rows].map((row) =>
    row.map((value) => quoteIfNeeded(cell(value), delimiter)).join(delimiter),
  );
  return lines.join("\r\n");
}

export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
