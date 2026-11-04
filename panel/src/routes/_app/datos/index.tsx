import { createFileRoute } from "@tanstack/react-router";
import { ComingSoonPage } from "@/components/coming-soon";

export const Route = createFileRoute("/_app/datos/")({
  component: () => <ComingSoonPage title="Datos" />,
});
