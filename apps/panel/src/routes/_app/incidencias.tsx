import { createFileRoute } from "@tanstack/react-router";
import { IncidentsPage } from "@/features/incidents/incidents-page";

export const Route = createFileRoute("/_app/incidencias")({
  component: IncidentsPage,
});
