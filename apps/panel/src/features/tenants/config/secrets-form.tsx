import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type SecretField = components["schemas"]["SecretField"];

function randomValue(): string {
  const bytes = new Uint8Array(36);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(36).padStart(2, "0"))
    .join("")
    .slice(0, 48);
}

export function SecretsForm({
  slug,
  fields,
}: {
  slug: string;
  fields: SecretField[];
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const client = useQueryClient();

  function reset() {
    setValues({});
    setError(false);
  }

  async function submit() {
    const secrets = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value !== ""),
    );
    if (Object.keys(secrets).length === 0) return;
    setPending(true);
    setError(false);
    try {
      const result = await api.PUT("/tenants/{slug}/secrets", {
        params: { path: { slug } },
        body: { secrets },
      });
      if (!result.response.ok) throw new Error();
      toast.success("Secretos sustituidos.");
      setOpen(false);
      reset();
      void client.invalidateQueries({ queryKey: ["tenant-secrets", slug] });
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          Cambiar credenciales
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Credenciales</DialogTitle>
          <DialogDescription>
            Lo que dejes en blanco conserva su valor actual.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {fields.map((field) => (
            <div key={field.name} className="space-y-1">
              <Label htmlFor={`secret-${field.name}`}>{field.label}</Label>
              <div className="flex gap-2">
                <Input
                  id={`secret-${field.name}`}
                  aria-label={field.label}
                  type="text"
                  autoComplete="off"
                  required={!field.set}
                  placeholder={
                    field.set ? "Dejar en blanco para conservar" : undefined
                  }
                  value={values[field.name] ?? ""}
                  onChange={(event) =>
                    setValues((current) => ({
                      ...current,
                      [field.name]: event.target.value,
                    }))
                  }
                />
                {field.generatable && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() =>
                      setValues((current) => ({
                        ...current,
                        [field.name]: randomValue(),
                      }))
                    }
                  >
                    Generar
                  </Button>
                )}
              </div>
              <p className="text-sm text-muted-foreground">{field.help}</p>
            </div>
          ))}
          {error && (
            <p role="alert">
              No se pudieron sustituir los secretos. Vuelve a introducirlos.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => setOpen(false)}
          >
            Cancelar
          </Button>
          <Button disabled={pending} onClick={() => void submit()}>
            Guardar secretos
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
