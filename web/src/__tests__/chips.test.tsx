import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, STATS, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const number = () => screen.getByTestId("big-number").textContent;

describe("chips choose which server number is displayed", () => {
  it("starts on All-time and switches to today's and the streak count", async () => {
    stubFetch({ entries: { body: [ENTRY] } });
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(number()).toBe(String(STATS.pages_all_time)));
    expect(screen.getByRole("button", { name: "All-time" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("pages, all time")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Today" }));
    expect(number()).toBe(String(STATS.pages_today));
    expect(screen.getByText("pages today")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Streak" }));
    expect(number()).toBe(String(STATS.current_streak_days));
    expect(screen.getByText("days in a row")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All-time" }));
    expect(number()).toBe(String(STATS.pages_all_time));
  });

  it("fetches nothing when a chip is clicked -- all three values are already loaded", async () => {
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(number()).toBe(String(STATS.pages_all_time)));
    const callsAfterLoad = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Today" }));
    await user.click(screen.getByRole("button", { name: "Streak" }));

    expect(fetchMock.mock.calls.length).toBe(callsAfterLoad);
  });
});
