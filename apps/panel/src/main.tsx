import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { setUnauthorizedHandler } from "@/api/client";
import { fetchCsrf } from "@/features/auth/api";
import { queryClient } from "@/lib/query-client";
import { router } from "@/router";
import "./styles/globals.css";

// Sets the CSRF cookie the login form will need; nothing in the UI
// depends on the result, so no need to await it before rendering.
fetchCsrf().catch(() => {});

setUnauthorizedHandler(() => {
  queryClient.removeQueries({ queryKey: ["me"] });
  router.navigate({
    to: "/login",
    search: { redirect: router.state.location.pathname },
  });
});

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
