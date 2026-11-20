import { expect, test } from "vitest";
import { errorDetail } from "./errors";

test("errorDetail appends the backend's details", () => {
  const error = {
    status: 422,
    message: "Entrada no válida.",
    details: ["secrets.bot_token: demasiado corto"],
  };
  expect(errorDetail(error, "x")).toBe(
    "Entrada no válida. secrets.bot_token: demasiado corto",
  );
  expect(errorDetail(new Error("boom"), "fallback")).toBe("fallback");
});
