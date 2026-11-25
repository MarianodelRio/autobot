import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  const fetching = () =>
    button.querySelector("svg")?.getAttribute("data-fetching");
  await waitFor(() => expect(fetching()).toBe("false"));
  await userEvent.click(button);
  await waitFor(() => expect(fetching()).toBe("true"));
  expect(queryFn).toHaveBeenCalledTimes(2);
  release();
  await waitFor(() => expect(fetching()).toBe("false"));
});
