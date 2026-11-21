import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
      routeFileIgnorePattern: "\\.test\\.tsx$",
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src"),
    },
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
      // The documentation site: `make docs` serves it on :8100 under /docs/, the same
      // path as in the production image (ADR-018).
      "/docs": { target: "http://localhost:8100", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    // One jsdom per worker instead of one per file (it was ~80% of the run time),
    // keeping each file isolated.
    pool: "vmThreads",
    environmentOptions: { jsdom: { url: "http://127.0.0.1:8000/" } },
    setupFiles: ["./src/vitest.setup.ts"],
  },
});
