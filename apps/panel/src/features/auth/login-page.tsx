import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type LoginPayload, login } from "./api";
import { meQueryOptions } from "./use-me";

const schema = z.object({
  username: z.string().min(1, "Falta el usuario."),
  password: z.string().min(1, "Falta la contraseña."),
  otp: z.string().regex(/^\d{6}$/, "El código tiene 6 dígitos."),
});

type FormValues = z.infer<typeof schema>;

const GENERIC_ERROR = "No se ha podido iniciar sesión.";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const mutation = useMutation<
    Awaited<ReturnType<typeof login>>,
    ApiError,
    LoginPayload
  >({
    mutationFn: login,
    onSuccess: (me) => {
      queryClient.setQueryData(meQueryOptions.queryKey, me);
      onSuccess();
    },
  });

  const apiError = mutation.error ?? undefined;

  return (
    <form
      className="mx-auto flex w-full max-w-sm flex-col gap-4"
      onSubmit={handleSubmit((values) => mutation.mutate(values))}
    >
      <div className="grid gap-2">
        <Label htmlFor="username">Usuario</Label>
        <Input
          id="username"
          autoComplete="username"
          {...register("username")}
        />
        {errors.username && (
          <p className="text-sm text-destructive">{errors.username.message}</p>
        )}
      </div>
      <div className="grid gap-2">
        <Label htmlFor="password">Contraseña</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          {...register("password")}
        />
        {errors.password && (
          <p className="text-sm text-destructive">{errors.password.message}</p>
        )}
      </div>
      <div className="grid gap-2">
        <Label htmlFor="otp">Código</Label>
        <Input
          id="otp"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          {...register("otp")}
        />
        {errors.otp && (
          <p className="text-sm text-destructive">{errors.otp.message}</p>
        )}
      </div>
      {apiError && (
        <p className="text-sm text-destructive">
          {apiError.message || GENERIC_ERROR}
        </p>
      )}
      <Button type="submit" disabled={mutation.isPending}>
        Entrar
      </Button>
    </form>
  );
}
