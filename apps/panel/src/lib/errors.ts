export function errorMessage(error: unknown, fallback: string): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    "message" in error &&
    typeof error.message === "string"
  )
    return error.message;
  return fallback;
}

/** The message plus the backend's `details` (a 422 lists which field failed). */
export function errorDetail(error: unknown, fallback: string): string {
  const message = errorMessage(error, fallback);
  if (
    typeof error === "object" &&
    error !== null &&
    "details" in error &&
    Array.isArray(error.details) &&
    error.details.length > 0
  )
    return `${message} ${error.details.join("; ")}`;
  return message;
}
