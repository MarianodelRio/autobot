import {
  Activity,
  Database,
  History,
  LayoutDashboard,
  ScrollText,
  Server,
  TriangleAlert,
  Users,
} from "lucide-react";

export interface NavSection {
  title: string;
  to: string;
  icon: typeof LayoutDashboard;
}

// Order: Resumen · Clientes · Actividad · Incidencias (n) · Logs · Datos ·
// Sistema · ─ · Auditoría · usuario · Salir. The divider before Auditoría is drawn
// by the sidebar, not encoded here.
export const NAV_SECTIONS: NavSection[] = [
  { title: "Resumen", to: "/", icon: LayoutDashboard },
  { title: "Clientes", to: "/clientes", icon: Users },
  { title: "Actividad", to: "/actividad", icon: Activity },
  { title: "Incidencias", to: "/incidencias", icon: TriangleAlert },
  { title: "Logs", to: "/logs", icon: ScrollText },
  { title: "Datos", to: "/datos", icon: Database },
  { title: "Sistema", to: "/sistema", icon: Server },
];

export const AUDIT_SECTION: NavSection = {
  title: "Auditoría",
  to: "/auditoria",
  icon: History,
};
