import type { FieldProps } from "@rjsf/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Service = {
  name: string;
  price_eur?: number | null;
  duration_min: number;
  client_presence_min: number;
};
type Services = Record<string, Service>;

const MAX_SERVICES = 9;

function nextId(existing: string[]): string {
  const used = new Set(existing.map(Number).filter((n) => Number.isInteger(n)));
  let n = 1;
  while (used.has(n)) n++;
  return String(n);
}

export function ServicesField({
  schema,
  formData,
  onChange,
  disabled,
  readonly,
  errorSchema,
  fieldPathId,
}: FieldProps<Services>) {
  const services = formData ?? {};
  const locked = Boolean(disabled || readonly);
  const ids = Object.keys(services);
  const errors = (errorSchema as { __errors?: string[] } | undefined)?.__errors;

  function update(id: string, current: Service, patch: Partial<Service>) {
    onChange({ ...services, [id]: { ...current, ...patch } }, fieldPathId.path);
  }
  function add() {
    onChange(
      {
        ...services,
        [nextId(ids)]: { name: "", duration_min: 30, client_presence_min: 30 },
      },
      fieldPathId.path,
    );
  }
  function remove(id: string) {
    const next = { ...services };
    delete next[id];
    onChange(next, fieldPathId.path);
  }

  return (
    <div className="space-y-3">
      {schema.title && <h3 className="font-medium">{schema.title}</h3>}
      {schema.description && (
        <p className="text-sm text-muted-foreground">{schema.description}</p>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nombre</TableHead>
            <TableHead>Precio (€)</TableHead>
            <TableHead>Duración (min)</TableHead>
            <TableHead>Presencia del cliente (min)</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {Object.entries(services).map(([id, service]) => {
            return (
              <TableRow key={id}>
                <TableCell>
                  <Input
                    value={service.name}
                    disabled={locked}
                    onChange={(event) =>
                      update(id, service, { name: event.target.value })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Input
                    type="number"
                    min={0}
                    step="0.01"
                    disabled={locked}
                    value={service.price_eur ?? ""}
                    onChange={(event) =>
                      update(id, service, {
                        price_eur:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Input
                    type="number"
                    min={1}
                    disabled={locked}
                    value={service.duration_min}
                    onChange={(event) =>
                      update(id, service, {
                        duration_min: Number(event.target.value),
                      })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Input
                    type="number"
                    min={1}
                    disabled={locked}
                    value={service.client_presence_min}
                    onChange={(event) =>
                      update(id, service, {
                        client_presence_min: Number(event.target.value),
                      })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={locked}
                    onClick={() => remove(id)}
                  >
                    Eliminar
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={locked || ids.length >= MAX_SERVICES}
        onClick={add}
      >
        Añadir servicio
      </Button>
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
