import { formatInTimeZone } from "date-fns-tz";

const MADRID = "Europe/Madrid";

export function formatDateTime(date: string | Date): string {
  return formatInTimeZone(date, MADRID, "dd/MM/yyyy HH:mm");
}

export function formatDate(date: string | Date): string {
  return formatInTimeZone(date, MADRID, "dd/MM/yyyy");
}

const RELATIVE_STEPS: [limit: number, divisor: number, unit: string][] = [
  [3600, 60, "min"],
  [86400, 3600, "h"],
];
const LAST_STEP: [divisor: number, unit: string] = [86400, "d"];

/** Compact relative time ("hace 12 s", "hace 3 min"), used across the Resumen screen. */
export function formatRelative(
  date: string | Date,
  now: Date = new Date(),
): string {
  const diffS = Math.max(
    0,
    Math.round((now.getTime() - new Date(date).getTime()) / 1000),
  );
  if (diffS === 0) return "justo ahora";
  if (diffS < 60) return `hace ${diffS} s`;
  const step = RELATIVE_STEPS.find(([limit]) => diffS < limit);
  const [divisor, unit] = step ? [step[1], step[2]] : LAST_STEP;
  return `hace ${Math.floor(diffS / divisor)} ${unit}`;
}

export function formatEur(value: number): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("es-ES", { useGrouping: true }).format(value);
}

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    BYTE_UNITS.length - 1,
  );
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value < 10 ? 1 : 0)} ${BYTE_UNITS[exponent]}`;
}
