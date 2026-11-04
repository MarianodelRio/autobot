import { createFileRoute } from "@tanstack/react-router";
import { CatalogPage } from "@/features/data/catalog-page";

export const Route = createFileRoute("/_app/datos/")({
  component: CatalogPage,
});
