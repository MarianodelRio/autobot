export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function downloadJson(filename: string, data: unknown): void {
  downloadBlob(
    filename,
    new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json;charset=utf-8;",
    }),
  );
}
