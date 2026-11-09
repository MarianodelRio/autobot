import {
  Database,
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

// Order: Resumen · Clientes · Incidencias (n) · Logs · Datos · Sistema · usuario · Salir.
export const NAV_SECTIONS: NavSection[] = [
  { title: "Resumen", to: "/", icon: LayoutDashboard },
  { title: "Clientes", to: "/clientes", icon: Users },
  { title: "Incidencias", to: "/incidencias", icon: TriangleAlert },
  { title: "Logs", to: "/logs", icon: ScrollText },
  { title: "Datos", to: "/datos", icon: Database },
  { title: "Sistema", to: "/sistema", icon: Server },
];
