import { createFileRoute } from "@tanstack/react-router";
import { DemoInvitesPage } from "@/features/demo-invites/demo-invites-page";

export const Route = createFileRoute("/_app/demo")({
  component: DemoInvitesPage,
});
