import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, statsWith, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the empty state", () => {
  it("renders no numeral at all before the first entry", async () => {
    stubFetch({
      stats: {
        body: statsWith({
          entry_count: 0,
          pages_today: 0,
          pages_all_time: 0,
          current_streak_days: 0,
          first_entry_date: null,
        }),
      },
      entries: { body: [] },
    });
    render(<App />);

    await waitFor(() => expect(screen.getByText(/first pages go here/i)).toBeInTheDocument());

    expect(screen.queryByTestId("big-number")).not.toBeInTheDocument();
    // And no chips either: there is no number for them to switch between.
    expect(screen.queryByRole("button", { name: "All-time" })).not.toBeInTheDocument();
  });

  it("renders a real 0 once something is logged -- a quiet morning is not an empty state", async () => {
    // 7am, one entry in the log from yesterday, nothing read today yet.
    stubFetch({
      stats: { body: statsWith({ entry_count: 1, pages_today: 0 }) },
      entries: { body: [ENTRY] },
    });
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(screen.getByTestId("big-number").textContent).toBe("0");
    expect(screen.queryByText(/first pages go here/i)).not.toBeInTheDocument();
  });

  it("brings the number back on the first save", async () => {
    const empty = statsWith({
      entry_count: 0,
      pages_today: 0,
      pages_all_time: 0,
      current_streak_days: 0,
      first_entry_date: null,
    });
    const saved = statsWith({ entry_count: 1, pages_today: 29, pages_all_time: 29 });

    let statsBody = empty;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST") {
        statsBody = saved;
        return new Response(JSON.stringify(ENTRY), { status: 201 });
      }
      if (url.includes("/api/quote")) return new Response(JSON.stringify({ quote: "hi" }));
      if (url.includes("/api/stats")) return new Response(JSON.stringify(statsBody));
      return new Response(JSON.stringify(statsBody === empty ? [] : [ENTRY]));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByText(/first pages go here/i)).toBeInTheDocument());

    await user.type(screen.getByLabelText("Start page"), "43");
    await user.type(screen.getByLabelText("End page"), "71");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());
    expect(screen.getByTestId("big-number").textContent).toBe("29");
  });
});
