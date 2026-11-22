import { type FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { setReauthPrompt } from "@/lib/reauth";
import { stepUp } from "./api";

/** Asks for a fresh TOTP code when the API answers `reauth_required`. Mount it once;
 * the API client opens it (see `lib/reauth.ts`) and resends the action on success. */
export function ReauthDialog() {
  const [open, setOpen] = useState(false);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const settle = useRef<((ok: boolean) => void) | null>(null);

  useEffect(
    () =>
      setReauthPrompt((resolve) => {
        settle.current = resolve;
        setOtp("");
        setError(null);
        setOpen(true);
      }),
    [],
  );

  function finish(ok: boolean) {
    setOpen(false);
    settle.current?.(ok);
    settle.current = null;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await stepUp(otp.trim());
      finish(true);
    } catch (err) {
      setError(errorMessage(err, "No se pudo verificar el código."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && finish(false)}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Confirma tu identidad</DialogTitle>
            <DialogDescription>
              Esta acción es sensible. Introduce un código nuevo de tu app de
              autenticación (no puede ser el que usaste al entrar).
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="reauth-otp">Código TOTP</Label>
            <Input
              id="reauth-otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={8}
              value={otp}
              onChange={(event) => setOtp(event.target.value)}
            />
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => finish(false)}
            >
              Cancelar
            </Button>
            <Button type="submit" disabled={busy || otp.trim().length < 6}>
              Confirmar
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
