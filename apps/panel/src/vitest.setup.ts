import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// jsdom has no layout engine, so it never implements scrollTo; the router's scroll
// restoration calls it on every navigation.
window.scrollTo ??= () => {};

// jsdom has no layout engine, so it never implements matchMedia; shadcn's
// sidebar (useIsMobile) needs it to exist.
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
