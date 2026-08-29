import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  CLASS,
  ENTRY,
  removePalette,
  setRailLayout,
  statsWith,
  stubFetch,
} from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  removePalette();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

async function boot(wide: boolean) {
  setRailLayout(wide);
  stubFetch({
    entries: { body: [ENTRY] },
    stats: { body: statsWith({ entry_count: 1 }) },
    classes: { body: [CLASS] },
  });
  render(<App />);
  await screen.findByLabelText("Start page");
}

/** The rail's own toggle, addressed by its accessible name -- the same word
 * the stacked <summary> uses, because the rails introduced no new copy. */
function tab(name: "Settings" | "Classes") {
  return screen.getByRole("button", { name, expanded: undefined }) as HTMLButtonElement;
}

describe("the edge rails (DECISIONS.md 17)", () => {
  it("puts Settings and Classes in rails on a wide window, both shut", async () => {
    await boot(true);

    for (const name of ["Settings", "Classes"] as const) {
      const toggle = screen.getByRole("button", { name });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(toggle.closest("aside")).toHaveAttribute("data-open", "false");
    }

    // The stacked cards are the other layout, not both at once: one body per
    // panel is mounted, never two.
    expect(document.querySelectorAll("details")).toHaveLength(0);
  });

  it("opens and closes a rail from its own button, and reports it", async () => {
    const user = userEvent.setup();
    await boot(true);

    const toggle = tab("Settings");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") as string);
    expect(panel).not.toBeNull();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle.closest("aside")).toHaveAttribute("data-open", "true");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.closest("aside")).toHaveAttribute("data-open", "false");
  });

  it("lets both rails be open at once", async () => {
    const user = userEvent.setup();
    await boot(true);

    await user.click(tab("Settings"));
    await user.click(tab("Classes"));

    expect(tab("Settings")).toHaveAttribute("aria-expanded", "true");
    expect(tab("Classes")).toHaveAttribute("aria-expanded", "true");
  });

  it("is operable from the keyboard", async () => {
    const user = userEvent.setup();
    await boot(true);

    const toggle = tab("Settings");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("never writes the open state to settings", async () => {
    const user = userEvent.setup();
    setRailLayout(true);
    const fetchMock = stubFetch({
      entries: { body: [ENTRY] },
      stats: { body: statsWith({ entry_count: 1 }) },
      classes: { body: [CLASS] },
    });
    render(<App />);
    await screen.findByLabelText("Start page");

    await user.click(tab("Settings"));
    await user.click(tab("Classes"));

    // The heartbeat is the only thing this page posts unprompted; opening a
    // rail must add nothing to that list, least of all a settings PATCH.
    const writes = fetchMock.mock.calls.filter(
      ([url, init]) =>
        ((init as RequestInit | undefined)?.method ?? "GET") !== "GET" &&
        !String(url).includes("/api/heartbeat"),
    );
    expect(writes).toHaveLength(0);
  });

  it("stacks both panels under the entry log on a narrow window", async () => {
    await boot(false);

    expect(screen.queryByRole("complementary", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Classes" })).toBeNull();

    for (const name of ["Settings", "Classes"] as const) {
      expect(screen.getByText(name).closest("details")).not.toBeNull();
      expect(screen.getByText(name).closest("details")).not.toHaveAttribute("open");
    }
  });
});
