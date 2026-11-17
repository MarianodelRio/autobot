import type { FieldProps } from "@rjsf/utils";

const DAYS = [
  ["lunes", "Lunes"],
  ["martes", "Martes"],
  ["miercoles", "Miércoles"],
  ["jueves", "Jueves"],
  ["viernes", "Viernes"],
  ["sabado", "Sábado"],
  ["domingo", "Domingo"],
] as const;

const TIME_CLASS =
  "rounded-md border border-input bg-transparent px-2 py-1 text-sm";

function splitRange(range: string): [string, string] {
  const [start = "09:00", end = "18:00"] = range.split("-");
  return [start, end];
}

export function OpeningHoursField({
  schema,
  formData,
  onChange,
  disabled,
  readonly,
  errorSchema,
}: FieldProps<Record<string, string[]>>) {
  const hours = formData ?? {};
  const locked = Boolean(disabled || readonly);
  const errors = (errorSchema as { __errors?: string[] } | undefined)?.__errors;

  function setDay(day: string, ranges: string[] | null) {
    const next = { ...hours };
    if (ranges === null || ranges.length === 0) delete next[day];
    else next[day] = ranges;
    onChange(next);
  }

  function updateRange(day: string, index: number, part: 0 | 1, time: string) {
    const ranges = [...(hours[day] ?? [])];
    const [start, end] = splitRange(ranges[index] ?? "09:00-18:00");
    ranges[index] = part === 0 ? `${time}-${end}` : `${start}-${time}`;
    setDay(day, ranges);
  }

  return (
    <div className="space-y-3">
      {schema.title && <h3 className="font-medium">{schema.title}</h3>}
      <div className="space-y-2">
        {DAYS.map(([key, label]) => {
          const ranges = hours[key] ?? [];
          const open = ranges.length > 0;
          return (
            <div
              key={key}
              className="flex flex-wrap items-start gap-3 border-b pb-2 last:border-b-0"
            >
              <label className="flex w-28 items-center gap-2 pt-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={open}
                  disabled={locked}
                  onChange={(event) =>
                    setDay(key, event.target.checked ? ["09:00-18:00"] : null)
                  }
                />
                {label}
              </label>
              {open ? (
                <div className="flex flex-1 flex-col gap-2">
                  {ranges.map((range, index) => {
                    const [start, end] = splitRange(range);
                    return (
                      <div
                        key={`${key}-${range}`}
                        className="flex items-center gap-2"
                      >
                        <input
                          type="time"
                          value={start}
                          disabled={locked}
                          onChange={(event) =>
                            updateRange(key, index, 0, event.target.value)
                          }
                          className={TIME_CLASS}
                        />
                        <span aria-hidden>–</span>
                        <input
                          type="time"
                          value={end}
                          disabled={locked}
                          onChange={(event) =>
                            updateRange(key, index, 1, event.target.value)
                          }
                          className={TIME_CLASS}
                        />
                        <button
                          type="button"
                          aria-label={`Quitar tramo de ${label.toLowerCase()}`}
                          disabled={locked}
                          onClick={() =>
                            setDay(
                              key,
                              ranges.length > 1
                                ? ranges.filter((_, i) => i !== index)
                                : null,
                            )
                          }
                          className="text-muted-foreground hover:text-destructive"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() => setDay(key, [...ranges, "09:00-18:00"])}
                    className="self-start text-sm text-muted-foreground hover:text-foreground"
                  >
                    + Añadir tramo
                  </button>
                </div>
              ) : (
                <span className="pt-1.5 text-sm text-muted-foreground">
                  Cerrado
                </span>
              )}
            </div>
          );
        })}
      </div>
      {errors && errors.length > 0 && (
        <ul role="alert" className="text-sm text-status-critical">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
