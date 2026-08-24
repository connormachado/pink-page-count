import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { FALLBACK_QUOTE } from "../quote";
import { ENTRY, QUOTE, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the daily quote", () => {
  it("shows what the server sent", async () => {
    stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);
    await waitFor(() => expect(screen.getByText(QUOTE)).toBeInTheDocument());
  });

  it("shows a message even when the quote request fails", async () => {
    stubFetch({ entries: { body: [ENTRY] }, quote: { status: 500, body: null } });
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());
    expect(screen.getByText(FALLBACK_QUOTE)).toBeInTheDocument();
  });

  it("asks the server once and never re-picks on its own", async () => {
    const fetchMock = stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);
    await waitFor(() => expect(screen.getByText(QUOTE)).toBeInTheDocument());

    const quoteCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/quote"),
    );
    expect(quoteCalls).toHaveLength(1);
  });
});
