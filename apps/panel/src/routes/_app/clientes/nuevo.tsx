import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { OnboardingPage } from "@/features/onboarding/onboarding-page";
export const Route = createFileRoute("/_app/clientes/nuevo")({
  component: OnboardingRoute,
});
function OnboardingRoute() {
  const navigate = useNavigate();
  return (
    <OnboardingPage
      onCreated={(slug) =>
        void navigate({
          to: "/clientes/$slug",
          params: { slug },
          search: { tab: "configuracion", section: "canal" },
        })
      }
    />
  );
}
