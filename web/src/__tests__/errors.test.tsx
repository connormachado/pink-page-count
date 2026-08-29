import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { placeMessage } from "../components/EntryForm";
import { QUOTE_BODY, SETTINGS, STATS, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SERVER_MESSAGE = "page_end (12) must be greater than or equal to page_start (40)";

describe("the error path shows what the server said", () => {
  it("renders the message out of {\"error\": ...} after a rejected save", async () => {
    stubFetch({ post: { status: 422, body: { error: SERVER_MESSAGE } } });
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Start page"), "40");
    await user.type(screen.getByLabelText("End page"), "12");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const shown = await screen.findByText(SERVER_MESSAGE);
    expect(shown).toBeInTheDocument();
    // Next to the input it is about, not floating at the top of the page.
    expect(screen.getByLabelText("End page")).toHaveAttribute(
      "aria-describedby",
      "page-end-error",
    );
    expect(shown).toHaveAttribute("id", "page-end-error");
    // No status code, no stack trace.
    expect(screen.queryByText(/422/)).not.toBeInTheDocument();
    // The displayed total is untouched: a failed save changes no number.
    expect(screen.getByTestId("big-number").textContent).toBe(String(STATS.pages_all_time));
  });

  it("says the app is not running instead of showing a zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<App />);

    expect(await screen.findByText(/isn't running right now/)).toBeInTheDocument();
    expect(screen.queryByTestId("big-number")).not.toBeInTheDocument();
  });

  it("puts each message beside the input it names", () => {
    expect(placeMessage(SERVER_MESSAGE)).toBe("end");
    expect(placeMessage("page_start (-3) must be 0 or greater")).toBe("start");
    expect(placeMessage("Something else entirely")).toBe("form");
  });
});

// AUDIT.md B4, DECISIONS.md 4.5. A save that could not be written used to come
// back as a 500 the front end read as "nobody answered", so the app announced it
// was not running -- while it was running, answering, and still showing her old
// total. These pin the three states apart.
const WRITE_FAILED =
  "That didn't save — the app couldn't write to your reading log. " +
  "Everything you logged before is still there.";

/** Type a session into the form and press Save. */
async function logASession(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Start page"), "40");
  await user.type(screen.getByLabelText("End page"), "58");
  await user.type(screen.getByLabelText("Note (optional)"), "chapter 4");
  await user.click(screen.getByRole("button", { name: "Save" }));
}

/** Answer every GET normally and every POST with a raw, JSON-less 5xx -- what
 * Starlette itself returns for an exception no handler caught. */
function stubBodylessPostFailure() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/api/entries")) {
        return new Response("Internal Server Error", {
          status: 500,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        });
      }
      if (url.includes("/api/heartbeat")) return new Response(null, { status: 204 });
      const body = url.includes("/api/stats")
        ? STATS
        : url.includes("/api/quote")
          ? QUOTE_BODY
          : [];
      return new Response(JSON.stringify(url.includes("/api/settings") ? SETTINGS : body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

describe("a save the server could not write", () => {
  it("says the save did not happen, and does not say the app is closed", async () => {
    stubFetch({ post: { status: 500, body: { error: WRITE_FAILED } } });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await logASession(user);

    expect(await screen.findByText(WRITE_FAILED)).toBeInTheDocument();
    // The three things the old message got wrong.
    expect(screen.queryByText(/isn't running right now/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByTestId("big-number").textContent).toBe(String(STATS.pages_all_time));
  });

  it("keeps the page numbers she typed", async () => {
    stubFetch({ post: { status: 500, body: { error: WRITE_FAILED } } });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await logASession(user);
    await screen.findByText(WRITE_FAILED);

    // Losing her typing on top of losing the save is the avoidable half of this.
    expect(screen.getByLabelText("Start page")).toHaveValue("40");
    expect(screen.getByLabelText("End page")).toHaveValue("58");
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("chapter 4");
  });

  it("does not claim the app isn't running when the 5xx carries no body", async () => {
    stubBodylessPostFailure();
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    await logASession(user);

    // This is the exact case AUDIT.md B4 verified end to end.
    expect(await screen.findByText(/didn't save/)).toBeInTheDocument();
    expect(screen.queryByText(/isn't running right now/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Start page")).toHaveValue("40");
  });

  it("still says the app is not running when nobody answers at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<App />);

    // The one error that may say this, and it still does.
    expect(await screen.findByText(/isn't running right now/)).toBeInTheDocument();
  });

  it("says the app is running when a load fails, not that it is closed", async () => {
    stubFetch({
      stats: { status: 500, body: { error: "boom" } },
      entries: { status: 500, body: { error: "boom" } },
      classes: { status: 500, body: { error: "boom" } },
      settings: { status: 500, body: { error: "boom" } },
    });
    render(<App />);

    expect(await screen.findByText(/The app is running/)).toBeInTheDocument();
    expect(screen.queryByText(/isn't running right now/)).not.toBeInTheDocument();
    // No zero standing in for a total nobody could read.
    expect(screen.queryByTestId("big-number")).not.toBeInTheDocument();
  });
});
