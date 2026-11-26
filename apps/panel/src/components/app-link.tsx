import { useRouter } from "@tanstack/react-router";
import type { MouseEvent, ReactNode } from "react";

/** Is `href` a screen of this panel (not the docs site served beside it, nor an
 * external page)? */
export function isPanelPath(href: string): boolean {
  return (
    href.startsWith("/") &&
    !href.startsWith("//") &&
    !href.startsWith("/docs") &&
    !href.startsWith("/api/")
  );
}

/** A link whose target arrives as text (from the API): inside the panel it navigates
 * with the router, like `<Link>` (no full page reload, the query cache survives);
 * anything else is a plain `<a>`. The real `href` stays, so Ctrl+clic, middle clic
 * and «abrir en otra pestaña» work as with any link. */
export function AppLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const internal = isPanelPath(href);
  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (
      !internal ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    router.history.push(href);
  }
  return (
    <a className={className} href={href} onClick={onClick}>
      {children}
    </a>
  );
}
