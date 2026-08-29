import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ATTRIBUTION_TOKEN, DailyQuote } from "../components/DailyQuote";
import { FALLBACK_QUOTE_TEXT } from "../quote";
import {
  ATTRIBUTION,
  ENTRY,
  QUOTE,
  UNATTRIBUTED_QUOTE_BODY,
  stubFetch,
} from "./helpers";

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
    expect(screen.getByText(FALLBACK_QUOTE_TEXT)).toBeInTheDocument();
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

/** DECISIONS.md 10.1 (amended). The rule these tests exist for is the second
 * describe block: an unattributed quote must render EXACTLY what it rendered
 * before this feature, down to there being no second element in the DOM. */
describe("attribution", () => {
  it("renders the attributor under the quote, with an em dash", async () => {
    stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);

    await waitFor(() => expect(screen.getByText(QUOTE)).toBeInTheDocument());
    expect(screen.getByTestId("quote-attribution")).toHaveTextContent(
      `— ${ATTRIBUTION}`,
    );
  });

  it("right-aligns the attributor and sets it smaller than the quote", () => {
    render(<DailyQuote quote={{ text: QUOTE, attribution: ATTRIBUTION }} />);
    const attribution = screen.getByTestId("quote-attribution");
    expect(attribution.className).toContain("text-right");
    expect(attribution.className).toContain("text-sm");
  });

  it("uses an existing theme token and hardcodes no color", () => {
    render(<DailyQuote quote={{ text: QUOTE, attribution: ATTRIBUTION }} />);
    const attribution = screen.getByTestId("quote-attribution");
    expect(attribution.className).toContain("text-[var(--rose-muted)]");
    expect(attribution.className).not.toMatch(/#[0-9a-fA-F]{3,6}/);
  });

  it("paints the token that contrast.test.ts checks", () => {
    // Closes the loop: the WCAG check runs against ATTRIBUTION_TOKEN, and this
    // asserts the rendered element actually uses it. Changing the color in one
    // place without the other fails here.
    render(<DailyQuote quote={{ text: QUOTE, attribution: ATTRIBUTION }} />);
    expect(screen.getByTestId("quote-attribution").className).toContain(
      `var(${ATTRIBUTION_TOKEN})`,
    );
  });

  it("keeps a second delimiter inside the attributor", () => {
    render(
      <DailyQuote quote={{ text: QUOTE, attribution: "A, quoted by B" }} />,
    );
    expect(screen.getByTestId("quote-attribution")).toHaveTextContent(
      "— A, quoted by B",
    );
  });
});

describe("an unattributed quote", () => {
  it("renders no attribution element at all", async () => {
    stubFetch({ entries: { body: [ENTRY] }, quote: { body: UNATTRIBUTED_QUOTE_BODY } });
    render(<App />);

    await waitFor(() => expect(screen.getByText(QUOTE)).toBeInTheDocument());
    expect(screen.queryByTestId("quote-attribution")).not.toBeInTheDocument();
  });

  it("renders no em dash anywhere in the quote block", () => {
    render(<DailyQuote quote={{ text: QUOTE, attribution: null }} />);
    expect(screen.getByTestId("quote-block").textContent).toBe(QUOTE);
  });

  it("adds no second child, so there is no space to reserve", () => {
    render(<DailyQuote quote={{ text: QUOTE, attribution: null }} />);
    expect(screen.getByTestId("quote-block").children).toHaveLength(1);
  });

  it("renders the same markup as the attributed case minus the attribution", () => {
    const { container: bare } = render(
      <DailyQuote quote={{ text: QUOTE, attribution: null }} />,
    );
    const bareHtml = bare.innerHTML;
    cleanup();
    const { container: credited } = render(
      <DailyQuote quote={{ text: QUOTE, attribution: ATTRIBUTION }} />,
    );
    // The attributed case is the bare case plus one element; the quote's own
    // paragraph is byte-identical between them.
    expect(credited.innerHTML.startsWith(bareHtml.replace("</div>", ""))).toBe(true);
  });

  it("treats a whitespace-only attribution as no attribution", async () => {
    stubFetch({
      entries: { body: [ENTRY] },
      quote: { body: { text: QUOTE, attribution: "   " } },
    });
    render(<App />);

    await waitFor(() => expect(screen.getByText(QUOTE)).toBeInTheDocument());
    expect(screen.queryByTestId("quote-attribution")).not.toBeInTheDocument();
  });
});
