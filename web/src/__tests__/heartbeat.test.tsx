import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Every POST this page has made to /api/heartbeat. */
function beats(fetchMock: ReturnType<typeof stubFetch>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/heartbeat"));
}

/** Pretend the tab is in the background. The point of these tests is that this
 * changes nothing: a hidden tab is still an open tab (DECISIONS.md 16.2). */
function hideTheTab() {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "hidden",
  });
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("the heartbeat", () => {
  it("beats as soon as the page opens", async () => {
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);

    await waitFor(() => expect(beats(fetchMock).length).toBeGreaterThan(0));
    expect(beats(fetchMock)[0][1]?.method).toBe("POST");
  });

  it("keeps beating on an interval", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);

    await waitFor(() => expect(beats(fetchMock)).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(beats(fetchMock)).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(beats(fetchMock)).toHaveLength(3);
  });

  it("keeps beating while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);
    await waitFor(() => expect(beats(fetchMock)).toHaveLength(1));

    hideTheTab();
    await vi.advanceTimersByTimeAsync(30_000);

    // Only closing the tab may stop this. Backgrounding it must not: she leaves
    // the page open in another window all evening and comes back to it.
    expect(beats(fetchMock)).toHaveLength(2);
  });

  it("stops when the page goes away, and not before", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    const view = render(<App />);
    await waitFor(() => expect(beats(fetchMock)).toHaveLength(1));

    view.unmount();
    await vi.advanceTimersByTimeAsync(120_000);

    // Unmounting is the closest a jsdom test gets to closing the tab. Four
    // intervals passed and nothing was sent -- which is what lets the server's
    // timeout mean "she has gone" rather than "the timer drifted".
    expect(beats(fetchMock)).toHaveLength(1);
  });

  it("says nothing when a beat fails", async () => {
    const fetchMock = stubFetch({
      entries: { body: [ENTRY] },
      heartbeat: { status: 500, body: null },
    });
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());
    await waitFor(() => expect(beats(fetchMock).length).toBeGreaterThan(0));

    // A failed keepalive is not an outage and is never reported as one. The
    // page she is reading must not be replaced by an error she cannot act on.
    expect(screen.queryByText(/isn't running right now/)).not.toBeInTheDocument();
  });
});
