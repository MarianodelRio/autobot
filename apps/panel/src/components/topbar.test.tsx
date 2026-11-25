import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ReloadButton } from "@/components/topbar";

function Probe({ queryFn }: { queryFn: () => Promise<string> }) {
  useQuery({ queryKey: ["x"], queryFn, staleTime: Infinity });
  return <ReloadButton />;
}

test("«Recargar» refetches the active queries and spins while fetching", async () => {
  let release: () => void = () => {};
  const queryFn = vi
    .fn<() => Promise<string>>()
    .mockResolvedValueOnce("first")
    .mockImplementationOnce(
      () => new Promise((resolve) => (release = () => resolve("second"))),
    );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Probe queryFn={queryFn} />
    </QueryClientProvider>,
  );
  const button = screen.getByRole("button", { name: "Recargar" });
  // The nuance goes in a description, not in the accessible name.
  expect(button).toHaveAccessibleDescription(/«Comprobar» se conservan/);
  expect(button).toHaveAttribute("aria-busy", "false");
  const fetching = () =>
    button.querySelector("svg")?.getAttribute("data-fetching");
  await waitFor(() => expect(fetching()).toBe("false"));
  await userEvent.click(button);
  await waitFor(() => expect(fetching()).toBe("true"));
  expect(button).toHaveAttribute("aria-busy", "true");
  expect(queryFn).toHaveBeenCalledTimes(2);
  release();
  await waitFor(() => expect(fetching()).toBe("false"));
  expect(button).toHaveAttribute("aria-busy", "false");
});

test("a background refetch does not make the button spin", async () => {
  const client = new QueryClient();
  const queryFn = vi.fn<() => Promise<string>>().mockResolvedValue("x");
  render(
    <QueryClientProvider client={client}>
      <Probe queryFn={queryFn} />
    </QueryClientProvider>,
  );
  const button = screen.getByRole("button", { name: "Recargar" });
  await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
  let release: () => void = () => {};
  queryFn.mockImplementationOnce(
    () => new Promise((resolve) => (release = () => resolve("y"))),
  );
  await act(async () => {
    void client.invalidateQueries({ queryKey: ["x"] });
  });
  await waitFor(() => expect(client.isFetching()).toBe(1));
  expect(button.querySelector("svg")?.getAttribute("data-fetching")).toBe(
    "false",
  );
  expect(button).toHaveAttribute("aria-busy", "false");
  release();
});
