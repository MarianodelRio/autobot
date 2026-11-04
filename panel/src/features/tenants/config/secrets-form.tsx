import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SecretsForm({
  slug,
  fields,
}: {
  slug: string;
  fields: string[];
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const client = useQueryClient();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = new FormData(form);
    const secrets = Object.fromEntries(
      fields.map((name) => [name, String(input.get(name) ?? "")]),
    );
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
      void client.invalidateQueries({ queryKey: ["tenant-secrets", slug] });
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
    } catch {
      setError(true);
    } finally {
      form.reset();
      setPending(false);
    }
  }
  if (!open)
    return (
      <Button
        onClick={() => {
          setError(false);
          setOpen(true);
        }}
      >
        Sustituir secretos
      </Button>
    );
  return (
    <form onSubmit={submit} autoComplete="off" className="space-y-3">
      <p>Sustituye todos los valores del canal.</p>
      {fields.map((field) => (
        <div key={field}>
          <Label htmlFor={`secret-${field}`}>{field}</Label>
          <Input
            id={`secret-${field}`}
            name={field}
            type="password"
            autoComplete="new-password"
            required
          />
        </div>
      ))}
      {error && (
        <p role="alert">
          No se pudieron sustituir los secretos. Vuelve a introducirlos.
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          Guardar secretos
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() => setOpen(false)}
        >
          Cancelar
        </Button>
      </div>
    </form>
  );
}
