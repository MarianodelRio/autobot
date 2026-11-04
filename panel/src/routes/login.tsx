import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { z } from "zod";
import { LoginPage } from "@/features/auth/login-page";

const searchSchema = z.object({ redirect: z.string().optional() });

export const Route = createFileRoute("/login")({
  validateSearch: searchSchema,
  component: LoginRoute,
});

function LoginRoute() {
  const navigate = useNavigate();
  const { redirect } = Route.useSearch();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background p-4">
      <h1 className="text-2xl font-semibold">Autobot</h1>
      <LoginPage onSuccess={() => navigate({ to: redirect || "/" })} />
    </div>
  );
}
