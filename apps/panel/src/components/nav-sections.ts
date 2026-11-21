import {
  BookOpen,
  Database,
  LayoutDashboard,
  QrCode,
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

// Order: Resumen · Clientes · Incidencias (n) · Demo · Logs · Datos · Sistema · usuario · Salir.
export const NAV_SECTIONS: NavSection[] = [
  { title: "Resumen", to: "/", icon: LayoutDashboard },
  { title: "Clientes", to: "/clientes", icon: Users },
  { title: "Incidencias", to: "/incidencias", icon: TriangleAlert },
  { title: "Demo", to: "/demo", icon: QrCode },
  { title: "Logs", to: "/logs", icon: ScrollText },
  { title: "Datos", to: "/datos", icon: Database },
  { title: "Sistema", to: "/sistema", icon: Server },
];

// Documentation site, served by the panel's Caddy under /docs/ (ADR-018). A plain link
// that opens in a new tab, not a route. In `make panel-dev`, Vite proxies /docs to
// `make docs` (see vite.config.ts).
export const DOCS_LINK = { title: "Docs", href: "/docs/", icon: BookOpen };
