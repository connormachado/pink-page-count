import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { NUMERAL_MAX_PX } from "../useNumeralFit";
import {
  CLASS,
  ENTRY,
  removePalette,
  setViewportWidth,
  statsWith,
  stubFetch,
} from "./helpers";

const ORIGINAL_WIDTH = window.innerWidth;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  removePalette();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  (window as unknown as { innerWidth: number }).innerWidth = ORIGINAL_WIDTH;
});

async function boot(stats: Partial<Parameters<typeof statsWith>[0]> = {}) {
  stubFetch({
    entries: { body: [ENTRY] },
    stats: { body: statsWith({ entry_count: 1, ...stats }) },
    classes: { body: [CLASS] },
  });
  render(<App />);
  await screen.findByLabelText("Start page");
}

/** The rail's own toggle, addressed by its accessible name -- the same word
 * the rail's label uses, because the rails introduced no new copy. */
function tab(name: "Settings" | "Classes") {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

function numeralFontSize() {
  const el = screen.getByTestId("big-number");
  return parseFloat(el.style.fontSize);
}

describe("the edge rails (DECISIONS.md 17)", () => {
  it("puts Settings and Classes in rails, both shut", async () => {
    await boot();

    for (const name of ["Settings", "Classes"] as const) {
      const toggle = screen.getByRole("button", { name });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(toggle.closest("aside")).toHaveAttribute("data-open", "false");
    }
  });

  it("opens and closes a rail from its own button, and reports it", async () => {
    const user = userEvent.setup();
    await boot();

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
    await boot();

    await user.click(tab("Settings"));
    await user.click(tab("Classes"));

    expect(tab("Settings")).toHaveAttribute("aria-expanded", "true");
    expect(tab("Classes")).toHaveAttribute("aria-expanded", "true");
  });

  it("is operable from the keyboard", async () => {
    const user = userEvent.setup();
    await boot();

    const toggle = tab("Settings");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("never writes the open state to settings", async () => {
    const user = userEvent.setup();
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

  // ------------------------------------------------------------------- //
  // No breakpoint: both rails exist at every width, and there is no
  // second layout for them to fall back to (DECISIONS.md 17.2).
  // ------------------------------------------------------------------- //

  it("mounts both rails without asking a media query anything", async () => {
    const asked: string[] = [];
    vi.stubGlobal("matchMedia", (query: string) => {
      asked.push(query);
      return {
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      };
    });

    await boot();

    expect(screen.getByRole("complementary", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Classes" })).toBeInTheDocument();
    // Motion still asks about reduced motion. Nothing asks about width.
    expect(asked.filter((query) => query.includes("width"))).toHaveLength(0);
  });

  it("stacks nothing under the entry log, at any width", async () => {
    await boot();

    setViewportWidth(900);
    expect(screen.getByRole("complementary", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Classes" })).toBeInTheDocument();

    // The stacked <details> pair is gone, not hidden: one body per panel, in
    // one frame, and no width brings a second copy back (17.4).
    expect(document.querySelectorAll("details")).toHaveLength(0);
    expect(screen.getAllByRole("complementary")).toHaveLength(2);
  });

  it("shrinks the numeral rather than the rails when the window narrows", async () => {
    await boot({ pages_all_time: 412 });

    setViewportWidth(1600);
    const wide = numeralFontSize();
    expect(wide).toBe(NUMERAL_MAX_PX);

    setViewportWidth(900);
    const narrow = numeralFontSize();
    expect(narrow).toBeLessThan(wide);

    // Still there, still the biggest thing on the page.
    expect(screen.getAllByRole("complementary")).toHaveLength(2);
    expect(narrow).toBeGreaterThan(48);
  });

  it("keeps the numeral's size to itself when a rail opens", async () => {
    const user = userEvent.setup();
    await boot({ pages_all_time: 412 });
    setViewportWidth(900);

    const shut = numeralFontSize();
    await user.click(tab("Settings"));
    await user.click(tab("Classes"));

    // The fit is measured against two *open* rails at every width, so opening
    // one changes nothing whatever about the center column (17.1).
    expect(numeralFontSize()).toBe(shut);
  });
});
