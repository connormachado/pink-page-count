import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { PAINT_CACHE_KEY } from "../theme";
import { chipFromSetting } from "../stat";
import { ENTRY, removePalette, settingsWith, statsWith, stubFetch } from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  removePalette();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  for (const token of ["--pink-hot", "--pink-wash", "--pink-surface", "--pink-edge", "--ink", "--rose-muted"]) {
    document.documentElement.style.removeProperty(token);
  }
});

async function boot(overrides: Parameters<typeof settingsWith>[0] = {}) {
  const fetchMock = stubFetch({
    entries: { body: [ENTRY] },
    stats: { body: statsWith({ entry_count: 1 }) },
    settings: { body: settingsWith(overrides) },
    settingsPatch: { body: settingsWith(overrides) },
  });
  render(<App />);
  await screen.findByLabelText("Start page");
  return fetchMock;
}

function bodyOf(fetchMock: ReturnType<typeof stubFetch>, method: string, path: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes(path) &&
      ((init as RequestInit | undefined)?.method ?? "GET") === method,
  );
  expect(call, `no ${method} to ${path}`).toBeTruthy();
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

function patchCallCount(fetchMock: ReturnType<typeof stubFetch>, path: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) =>
      String(url).includes(path) &&
      ((init as RequestInit | undefined)?.method ?? "GET") === "PATCH",
  ).length;
}

async function openSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("Settings"));
  return within(screen.getByRole("complementary", { name: "Settings" }));
}

/** The main chip row, scoped away from the settings panel's own default-chip
 * control -- both use the same three labels ("All-time"/"Today"/"Streak"),
 * and a closed rail's panel is still queryable in jsdom (its visibility is
 * CSS, which these tests do not load), so an unscoped query is ambiguous. */
function chipsGroup() {
  return within(screen.getByRole("group", { name: "Which number to show" }));
}

// --------------------------------------------------------------------------- //
// chipFromSetting (pure)
// --------------------------------------------------------------------------- //

describe("chipFromSetting", () => {
  it("maps all_time to all", () => {
    expect(chipFromSetting("all_time")).toBe("all");
  });
  it("maps today to today", () => {
    expect(chipFromSetting("today")).toBe("today");
  });
  it("maps streak to streak", () => {
    expect(chipFromSetting("streak")).toBe("streak");
  });
});

// --------------------------------------------------------------------------- //
// default_chip drives the chip selected on load (the spec's literal bullet)
// --------------------------------------------------------------------------- //

describe("default_chip", () => {
  it("drives the chip selected on load", async () => {
    await boot({ default_chip: "streak" });
    expect(chipsGroup().getByRole("button", { name: "Streak" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("a manual chip selection survives an unrelated change refresh", async () => {
    const user = userEvent.setup();
    await boot({ default_chip: "all_time" });

    await user.click(chipsGroup().getByRole("button", { name: "Today" }));
    expect(chipsGroup().getByRole("button", { name: "Today" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Any ordinary "change" refresh -- switching the theme preset via the
    // settings panel is one, and it has nothing to do with default_chip.
    const panel = await openSettings(user);
    await user.click(panel.getByRole("button", { name: "Jewel" }));

    await waitFor(() =>
      expect(chipsGroup().getByRole("button", { name: "Today" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
  });

  it("changing the setting via the panel does not move the currently displayed chip", async () => {
    const user = userEvent.setup();
    const fetchMock = await boot({ default_chip: "all_time" });

    const panel = await openSettings(user);
    await user.click(panel.getByRole("button", { name: "Today" }));

    await waitFor(() => expect(patchCallCount(fetchMock, "/api/settings")).toBeGreaterThan(0));
    expect(bodyOf(fetchMock, "PATCH", "/api/settings")).toEqual({ default_chip: "today" });
    // The main chip row is unaffected -- "All-time" is still the one shown.
    expect(chipsGroup().getByRole("button", { name: "All-time" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

// --------------------------------------------------------------------------- //
// First paint: the paint cache and reconciliation
// --------------------------------------------------------------------------- //

describe("theme reconciliation", () => {
  it("a cleared paint cache still resolves the correct theme from the API", async () => {
    // No data-theme pre-set at all -- simulates the boot script finding an
    // empty/cleared cache and no-opping.
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();

    await boot({ theme: "jewel" });

    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-theme")).toBe("jewel"),
    );
  });

  it("overwrites a stale cached theme with the one the server returns", async () => {
    document.documentElement.setAttribute("data-theme", "midnight");

    await boot({ theme: "cool" });

    await waitFor(() =>
      expect(document.documentElement.getAttribute("data-theme")).toBe("cool"),
    );
  });

  it("writes the resolved theme into the paint cache after a load", async () => {
    await boot({ theme: "neutral" });

    await waitFor(() => expect(localStorage.getItem(PAINT_CACHE_KEY)).not.toBeNull());
    const cached = JSON.parse(localStorage.getItem(PAINT_CACHE_KEY) as string);
    expect(cached.theme).toBe("neutral");
  });

  it("clears a stale inline override once custom_theme goes back to null", async () => {
    document.documentElement.style.setProperty("--rose-muted", "#ff0000");

    await boot({ theme: "pink", custom_theme: null });

    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue("--rose-muted")).toBe(""),
    );
  });
});

// --------------------------------------------------------------------------- //
// The settings panel is the collapsed pattern
// --------------------------------------------------------------------------- //

describe("the settings panel", () => {
  it("is closed by default", async () => {
    await boot();
    const rail = screen.getByRole("complementary", { name: "Settings" });
    expect(rail).toHaveAttribute("data-open", "false");
    expect(within(rail).getByRole("button", { name: "Settings" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

// --------------------------------------------------------------------------- //
// The theme editor
// --------------------------------------------------------------------------- //

const FULL_CUSTOM_THEME = {
  "--pink-hot": "#ff2e88",
  "--pink-wash": "#fff5f8",
  "--pink-surface": "#ffe8f0",
  "--pink-edge": "#ffc2da",
  "--ink": "#2b1a22",
  "--rose-muted": "#7a2e52",
};

describe("the theme editor", () => {
  it("clicking a preset PATCHes theme and clears custom_theme", async () => {
    const user = userEvent.setup();
    const fetchMock = await boot();

    const panel = await openSettings(user);
    await user.click(panel.getByRole("button", { name: "Jewel" }));

    await waitFor(() => expect(patchCallCount(fetchMock, "/api/settings")).toBeGreaterThan(0));
    expect(bodyOf(fetchMock, "PATCH", "/api/settings")).toEqual({
      theme: "jewel",
      custom_theme: null,
    });
  });

  it("previews live on input with no network call yet, then commits on change", async () => {
    const user = userEvent.setup();
    const fetchMock = await boot({
      theme: "custom",
      custom_theme: FULL_CUSTOM_THEME,
    });

    const panel = await openSettings(user);
    const input = panel.getByLabelText("Primary number") as HTMLInputElement;

    // fireEvent gives finer control over input vs. change than userEvent here.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.input(input, { target: { value: "#00ff00" } });

    expect(document.documentElement.style.getPropertyValue("--pink-hot")).toBe("#00ff00");
    expect(patchCallCount(fetchMock, "/api/settings")).toBe(0);

    fireEvent.change(input, { target: { value: "#00ff00" } });

    await waitFor(() => expect(patchCallCount(fetchMock, "/api/settings")).toBeGreaterThan(0));
    const body = bodyOf(fetchMock, "PATCH", "/api/settings");
    expect(body.theme).toBe("custom");
    expect(body.custom_theme["--pink-hot"]).toBe("#00ff00");
  });

  it("warns, but still allows the change to commit, when a pair falls below 4.5:1", async () => {
    const user = userEvent.setup();
    const fetchMock = await boot({
      theme: "custom",
      custom_theme: FULL_CUSTOM_THEME,
    });

    const panel = await openSettings(user);
    const inkInput = panel.getByLabelText("Main text") as HTMLInputElement;

    const { fireEvent } = await import("@testing-library/react");
    // Nearly the same color as the surface it sits on -- illegible on purpose.
    fireEvent.input(inkInput, { target: { value: "#ffe9f1" } });

    expect(await panel.findByRole("status")).toHaveTextContent(/hard to read/);

    fireEvent.change(inkInput, { target: { value: "#ffe9f1" } });
    await waitFor(() => expect(patchCallCount(fetchMock, "/api/settings")).toBeGreaterThan(0));
  });

  it("the reset-to-preset escape hatch stays reachable after an illegible edit", async () => {
    const user = userEvent.setup();
    const fetchMock = await boot({
      theme: "custom",
      custom_theme: { ...FULL_CUSTOM_THEME, "--ink": "#ffe9f1" },
    });

    const panel = await openSettings(user);
    const resetButton = panel.getByRole("button", { name: "Reset to preset" });
    expect(resetButton).toBeVisible();

    await user.click(resetButton);

    await waitFor(() => expect(patchCallCount(fetchMock, "/api/settings")).toBeGreaterThan(0));
    expect(bodyOf(fetchMock, "PATCH", "/api/settings")).toEqual({ custom_theme: null });
  });
});
