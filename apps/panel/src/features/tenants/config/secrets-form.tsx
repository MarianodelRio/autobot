import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, normalizeError } from "@/api/client";
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
import { errorDetail } from "@/lib/errors";

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
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const client = useQueryClient();

  function reset() {
    setValues({});
    setError(null);
  }

  async function submit() {
    const secrets = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value !== ""),
    );
    if (Object.keys(secrets).length === 0) return;
    setPending(true);
    setError(null);
    try {
      const result = await api.PUT("/tenants/{slug}/secrets", {
        params: { path: { slug } },
        body: { secrets },
      });
      if (!result.response.ok)
        throw normalizeError(result.error, result.response.status);
      // C10: the backend re-registers the Telegram webhook right after a change
      // (the old one would otherwise stay registered with the previous secret).
      if (result.data?.telegram_webhook_registered === false) {
        toast.warning(
          "Secretos sustituidos, pero no se pudo volver a registrar el webhook de Telegram. Regístralo desde el canal.",
        );
      } else {
        toast.success("Secretos sustituidos.");
      }
      setOpen(false);
      reset();
      void client.invalidateQueries({ queryKey: ["tenant-secrets", slug] });
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["tenant-webhook", slug] });
    } catch (caught) {
      // The typed values stay in the form: only a success clears them.
      setError(
        errorDetail(caught, "No se pudieron sustituir los secretos.") +
          " Los valores siguen en el formulario.",
      );
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
            <p role="alert" className="text-sm text-destructive">
              {error}
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
