import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ENTRY, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the backup link", () => {
  it("points straight at /api/export -- no fetch/blob JS involved", async () => {
    stubFetch({ entries: { body: [ENTRY] } });
    render(<App />);

    await waitFor(() => expect(screen.getByTestId("big-number")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: "Download a backup" })).toHaveAttribute(
      "href",
      "/api/export",
    );
  });
});
