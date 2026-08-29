import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, SETTINGS, setReducedMotion, statsWith } from "./helpers";
import type { Stats } from "../types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
});

function stubBackend(before: Stats, after: Stats) {
  let current = before;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if ((init?.method ?? "GET").toUpperCase() === "POST") {
      current = after;
      return new Response(JSON.stringify(ENTRY), { status: 201 });
    }
    if (url.includes("/api/quote")) return new Response(JSON.stringify({ quote: "hi" }));
    if (url.includes("/api/stats")) return new Response(JSON.stringify(current));
    if (url.includes("/api/settings")) return new Response(JSON.stringify(SETTINGS));
    if (url.includes("/api/classes")) return new Response(JSON.stringify([]));
    return new Response(JSON.stringify([ENTRY]));
  });
}

/** Take manual control of the frame loop so a test can look at the number
 * mid-flight instead of guessing at timing. */
function stubFrames() {
  const queue: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    queue.push(cb);
    return queue.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  return {
    /** Run the frame that is waiting, at `ms` into the animation. */
    advance(ms: number) {
      const next = queue.pop();
      queue.length = 0;
      if (next) act(() => next(performance.now() + ms));
    },
  };
}

const at = (total: number) => statsWith({ pages_all_time: total, entry_count: 4 });

async function saveAnEntry() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Start page"), "1");
  await user.type(screen.getByLabelText("End page"), "10");
  await user.click(screen.getByRole("button", { name: "Save" }));
}

const numeral = () => screen.getByTestId("big-number").textContent;
const announced = () => screen.getByTestId("big-number-announcement").textContent ?? "";

describe("the count-up", () => {
  it("lands on the server's value, having passed through values in between", async () => {
    const frames = stubFrames();
    stubBackend(at(400), at(500));
    render(<App />);
    await waitFor(() => expect(numeral()).toBe("400"));

    await saveAnEntry();
    // The frame loop is ours to drive, so the numeral holds until we run one.
    await waitFor(() => expect(announced()).toContain("500"));
    expect(numeral()).toBe("400");

    frames.advance(200);
    const midway = Number(numeral());
    expect(midway).toBeGreaterThan(400);
    expect(midway).toBeLessThan(500);

    // Past the full --dur-count, it settles on exactly what the server said.
    frames.advance(5000);
    expect(numeral()).toBe("500");
  });

  it("announces the final value once, not every frame of the animation", async () => {
    const frames = stubFrames();
    stubBackend(at(400), at(500));
    render(<App />);
    await waitFor(() => expect(numeral()).toBe("400"));

    await saveAnEntry();
    await waitFor(() => expect(announced()).toContain("500"));

    // Mid-flight the visible numeral is still climbing -- and it is aria-hidden,
    // so the intermediate values are never read out.
    frames.advance(200);
    expect(numeral()).not.toBe("500");
    expect(screen.getByTestId("big-number")).toHaveAttribute("aria-hidden", "true");
    expect(announced()).toContain("500");
  });

  it("with reduced motion the number changes instantly and correctly", async () => {
    setReducedMotion(true);
    const rafSpy = vi.fn();
    vi.stubGlobal("requestAnimationFrame", rafSpy);
    stubBackend(at(400), at(500));
    render(<App />);
    await waitFor(() => expect(numeral()).toBe("400"));

    await saveAnEntry();

    await waitFor(() => expect(numeral()).toBe("500"));
    expect(rafSpy).not.toHaveBeenCalled();
  });

  it("does not animate when a chip changes the number", async () => {
    const rafSpy = vi.fn();
    stubBackend(at(400), at(400));
    render(<App />);
    await waitFor(() => expect(numeral()).toBe("400"));

    vi.stubGlobal("requestAnimationFrame", rafSpy);
    const user = userEvent.setup();
    // Scoped away from the settings panel's own default-chip control, which
    // reuses the same three labels (DECISIONS.md 13).
    const chips = within(screen.getByRole("group", { name: "Which number to show" }));
    await user.click(chips.getByRole("button", { name: "Today" }));

    expect(numeral()).toBe(String(statsWith({}).pages_today));
    expect(rafSpy).not.toHaveBeenCalled();
  });
});
