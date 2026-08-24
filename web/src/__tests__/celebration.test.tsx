import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, setReducedMotion, statsWith } from "./helpers";
import type { Stats } from "../types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** A backend whose all-time total moves from `before` to `after` when the log is
 * mutated. Both numbers are served by the fake server, exactly as the real one
 * would -- the client never computes either of them. */
function stubBackend(before: Stats, after: Stats) {
  let current = before;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (method === "POST") {
      current = after;
      return new Response(JSON.stringify(ENTRY), { status: 201 });
    }
    if (method === "DELETE") {
      current = after;
      return new Response(null, { status: 204 });
    }
    if (method === "PATCH") {
      current = after;
      return new Response(JSON.stringify(ENTRY), { status: 200 });
    }
    if (url.includes("/api/quote")) return new Response(JSON.stringify({ quote: "hi" }));
    if (url.includes("/api/stats")) return new Response(JSON.stringify(current));
    return new Response(JSON.stringify([ENTRY]));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function saveAnEntry(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Start page"), "1");
  await user.type(screen.getByLabelText("End page"), "10");
  await user.click(screen.getByRole("button", { name: "Save" }));
}

const at = (total: number) => statsWith({ pages_all_time: total, entry_count: 4 });

describe("milestone celebrations", () => {
  it("fires when a save crosses a threshold", async () => {
    stubBackend(at(999), at(1002));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await saveAnEntry(user);

    await waitFor(() => expect(screen.getByTestId("milestone")).toBeInTheDocument());
    expect(screen.getByTestId("milestone")).toHaveTextContent("1,000 pages");
  });

  it("does not fire on a save that crosses nothing", async () => {
    stubBackend(at(1002), at(1005));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await saveAnEntry(user);

    await waitFor(() => expect(screen.getByTestId("big-number").textContent).toBe("1005"));
    expect(screen.queryByTestId("milestone")).not.toBeInTheDocument();
  });

  it("does not fire on a plain page load, however high the total already is", async () => {
    stubBackend(at(5000), at(5000));
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number").textContent).toBe("5000"));
    expect(screen.queryByTestId("milestone")).not.toBeInTheDocument();
  });

  it("does not fire when a delete drops the total back below a threshold", async () => {
    stubBackend(at(1002), at(998));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^Delete pages/ }));
    await user.click(screen.getByRole("button", { name: "Yes, remove" }));

    await waitFor(() => expect(screen.getByTestId("big-number").textContent).toBe("998"));
    expect(screen.queryByTestId("milestone")).not.toBeInTheDocument();
  });

  it("stays quiet on an edit that crosses upward -- only a new entry celebrates", async () => {
    stubBackend(at(999), at(1002));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^Edit pages/ }));
    // The new-entry form has an "End page" too; this one belongs to the row.
    const row = within(screen.getByRole("listitem"));
    await user.clear(row.getByLabelText("End page"));
    await user.type(row.getByLabelText("End page"), "171");
    await user.click(row.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.getByTestId("big-number").textContent).toBe("1002"));
    expect(screen.queryByTestId("milestone")).not.toBeInTheDocument();
  });

  it("never says how far away anything is", async () => {
    stubBackend(at(999), at(1002));
    const user = userEvent.setup();
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await saveAnEntry(user);
    await waitFor(() => expect(screen.getByTestId("milestone")).toBeInTheDocument());

    // DECISIONS.md 8: celebrate arrivals, never announce distances.
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/to go|away|remaining|left|until|next milestone|\d+%/i);
    expect(container.querySelector("progress")).toBeNull();
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("shows the message but creates no canvas with reduced motion", async () => {
    setReducedMotion(true);
    stubBackend(at(999), at(1002));
    const user = userEvent.setup();
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await saveAnEntry(user);

    await waitFor(() => expect(screen.getByTestId("milestone")).toBeInTheDocument());
    expect(container.querySelector("canvas")).toBeNull();
  });
});
