import { describe, expect, test } from "vitest";
import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatEur,
  formatNumber,
  formatRelative,
} from "./format";

describe("formatDateTime", () => {
  test("renders in Europe/Madrid, winter (CET, UTC+1)", () => {
    expect(formatDateTime("2026-11-04T22:30:00Z")).toBe("04/11/2026 23:30");
  });

  test("renders in Europe/Madrid, summer (CEST, UTC+2)", () => {
    expect(formatDateTime("2026-06-04T22:30:00Z")).toBe("05/06/2026 00:30");
  });
});

test("formatDate", () => {
  expect(formatDate("2026-11-04T22:30:00Z")).toBe("04/11/2026");
});

describe("formatRelative", () => {
  const now = new Date("2026-11-04T12:00:12Z");

  test("seconds", () => {
    expect(formatRelative("2026-11-04T12:00:00Z", now)).toBe("hace 12 s");
  });

  test("minutes", () => {
    expect(formatRelative("2026-11-04T11:57:12Z", now)).toBe("hace 3 min");
  });

  test("hours", () => {
    expect(formatRelative("2026-11-04T09:00:12Z", now)).toBe("hace 3 h");
  });

  test("days", () => {
    expect(formatRelative("2026-11-01T12:00:12Z", now)).toBe("hace 3 d");
  });

  test("now", () => {
    expect(formatRelative(now, now)).toBe("justo ahora");
  });
});

test("formatEur", () => {
  expect(formatEur(12.4)).toBe("12,40 €");
});

test("formatNumber", () => {
  expect(formatNumber(1240)).toBe("1.240");
});

describe("formatBytes", () => {
  test("bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
  });

  test("kilobytes", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
  });

  test("megabytes", () => {
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
