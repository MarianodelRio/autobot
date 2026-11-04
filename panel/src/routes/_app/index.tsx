import { createFileRoute } from "@tanstack/react-router";
import { ComingSoonPage } from "@/components/coming-soon";

export const Route = createFileRoute("/_app/")({
  component: () => <ComingSoonPage title="Resumen" />,
});
