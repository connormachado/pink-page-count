import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { placeMessage } from "../components/EntryForm";
import { STATS, stubFetch } from "./helpers";

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
