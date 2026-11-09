import { createFileRoute } from "@tanstack/react-router";
import { DataPage } from "@/features/data/data-page";

export const Route = createFileRoute("/_app/datos/")({
  component: DataPage,
});
