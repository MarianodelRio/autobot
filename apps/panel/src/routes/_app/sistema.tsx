import { createFileRoute } from "@tanstack/react-router";
import { SystemPage } from "@/features/system/system-page";

export const Route = createFileRoute("/_app/sistema")({
  component: SystemPage,
});
