import type { WidgetProps } from "@rjsf/utils";
import { cn } from "cn";

const ZONES: string[] =
  "supportedValuesOf" in Intl
    ? Intl.supportedValuesOf("timeZone")
    : ["Europe/Madrid"];

export function TimezoneSelect({
  id,
  value,
  required,
  disabled,
  onChange,
}: {
  id?: string;
  value: string | undefined;
  required?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const options = value && !ZONES.includes(value) ? [value, ...ZONES] : ZONES;
  return (
    <select
      id={id}
      required={required}
      disabled={disabled}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-xs outline-none md:text-sm dark:bg-input/30",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
      )}
    >
      {!value && <option value="">Elige una zona horaria</option>}
      {options.map((zone) => (
        <option key={zone} value={zone}>
          {zone}
        </option>
      ))}
    </select>
  );
}

export function TimezoneWidget({
  id,
  value,
  required,
  disabled,
  readonly,
  onChange,
}: WidgetProps) {
  return (
    <TimezoneSelect
      id={id}
      value={value}
      required={required}
      disabled={disabled || readonly}
      onChange={onChange}
    />
  );
}
