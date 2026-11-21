import { CircleHelp } from "lucide-react";

// The documentation site is served by the panel's own Caddy under /docs/ (ADR-018).
// It is a plain link, not a TanStack route: the page is a separate static site.
export const DOCS_BASE = "/docs/";

export function docsHref(page: string): string {
  return `${DOCS_BASE}${page.replace(/^\/+/, "")}`;
}

/** The «?» of a page header: opens that screen's procedure in the docs, in a new tab. */
export function HelpLink({ page }: { page: string }) {
  return (
    <a
      href={docsHref(page)}
      target="_blank"
      rel="noopener"
      aria-label="Ayuda: abrir la documentación de esta pantalla"
      title="Ayuda"
      className="inline-flex size-6 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <CircleHelp className="size-4" />
    </a>
  );
}
