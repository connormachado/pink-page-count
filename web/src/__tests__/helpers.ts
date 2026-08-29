import { vi } from "vitest";
import { CLASS_TOKENS } from "../palette";
import { RAIL_MIN_WIDTH_PX } from "../useRailLayout";
import type { Class, Entry, Settings, Stats } from "../types";

export const STATS: Stats = {
  pages_today: 29,
  pages_all_time: 412,
  current_streak_days: 5,
  entry_count: 17,
  first_entry_date: "2026-07-30",
};

export const ENTRY: Entry = {
  id: "3f2a1c8e-5b7d-4e19-9c02-8a6f1d4b7e30",
  page_start: 43,
  page_end: 71,
  pages: 29,
  read_at: "2026-08-24T21:12:00-04:00",
  note: "chapter 4",
  class_id: null,
  created_at: "2026-08-24T21:12:03-04:00",
  updated_at: "2026-08-24T21:12:03-04:00",
};

export const CLASS: Class = {
  id: "b81d0e4a-2c9f-4a13-8f77-1e5c9d3a2b60",
  title: "Bio 12",
  description: null,
  color: "#E4557F",
  archived: false,
  created_at: "2026-08-25T09:04:11-04:00",
  updated_at: "2026-08-25T09:04:11-04:00",
};

export const SETTINGS: Settings = {
  theme: "pink",
  custom_theme: null,
  default_chip: "all_time",
};

/** A settings payload with the fields a test cares about, defaults for the rest. */
export function settingsWith(overrides: Partial<Settings>): Settings {
  return { ...SETTINGS, ...overrides };
}

/** An entry with the fields a test cares about, defaults for the rest. */
export function entryWith(overrides: Partial<Entry>): Entry {
  return { ...ENTRY, ...overrides };
}

/** A class with the fields a test cares about. `id` defaults from the title so
 * two calls do not collide. */
export function classWith(overrides: Partial<Class>): Class {
  return { ...CLASS, id: overrides.title ?? CLASS.id, ...overrides };
}

/** Define the --class-* tokens on the document.
 *
 * vitest runs with css: false, so tokens.css is never loaded and the palette
 * resolves empty. These are placeholder values on purpose: the real ones live
 * in tokens.css and nowhere else (DECISIONS.md 12.2), and what these tests
 * assert is the *choosing*, not the colors. */
export function installPalette(): string[] {
  const colors = CLASS_TOKENS.map((_, i) => `#00000${i}`);
  CLASS_TOKENS.forEach((token, i) => {
    document.documentElement.style.setProperty(token, colors[i]);
  });
  return colors;
}

export function removePalette() {
  CLASS_TOKENS.forEach((token) => {
    document.documentElement.style.removeProperty(token);
  });
}

export const QUOTE = "A book met you where you were today, and that was enough.";

type Route = { status?: number; body?: unknown };

/** Stub fetch. No test in this file ever talks to a live backend. */
export function stubFetch(routes: {
  stats?: Route;
  entries?: Route;
  quote?: Route;
  classes?: Route;
  settings?: Route;
  post?: Route;
  patch?: Route;
  delete?: Route;
  classPost?: Route;
  classPatch?: Route;
  classDelete?: Route;
  settingsPatch?: Route;
  heartbeat?: Route;
}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    // The keepalive of DECISIONS.md 16.2. Matched before the method branches
    // below so it can never fall through into `routes.post` and be answered --
    // or counted -- as an entry being saved.
    if (url.includes("/api/heartbeat")) {
      const beat = routes.heartbeat ?? { status: 204 };
      const beatStatus = beat.status ?? 204;
      return new Response(beatStatus === 204 ? null : JSON.stringify(beat.body ?? null), {
        status: beatStatus,
        headers: { "Content-Type": "application/json" },
      });
    }

    const isClass = url.includes("/api/classes");
    const isSettings = url.includes("/api/settings");

    let route: Route | undefined;
    if (method === "POST")
      route = isClass ? (routes.classPost ?? { status: 201, body: CLASS }) : routes.post;
    else if (method === "PATCH")
      route = isSettings
        ? (routes.settingsPatch ?? { body: SETTINGS })
        : isClass
          ? (routes.classPatch ?? { body: CLASS })
          : routes.patch;
    else if (method === "DELETE")
      route = (isClass ? routes.classDelete : routes.delete) ?? { status: 204 };
    else if (url.includes("/api/quote")) route = routes.quote ?? { body: { quote: QUOTE } };
    else if (url.includes("/api/stats")) route = routes.stats ?? { body: STATS };
    else if (isSettings) route = routes.settings ?? { body: SETTINGS };
    else if (isClass) route = routes.classes ?? { body: [] };
    else if (url.includes("/api/entries")) route = routes.entries ?? { body: [] };

    const status = route?.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(route?.body ?? null), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}


/** Answer the prefers-reduced-motion query the way a test needs it.
 *
 * Every animation in the app is gated on this, so a test that asserts the
 * reduced-motion behaviour has to be able to say so. Cleared by
 * vi.unstubAllGlobals() in each file's afterEach. */
export function setReducedMotion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({
      matches: reduced && query.includes("prefers-reduced-motion: reduce"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  );
}

/** Answer the rail breakpoint query the way a test needs it.
 *
 * The default stub in test-setup.ts answers false to everything, so every
 * test that does not call this sees the stacked layout -- which is what the
 * whole suite predating the rails was written against (DECISIONS.md 17).
 * Cleared by vi.unstubAllGlobals() in each file's afterEach. */
export function setRailLayout(wide: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({
      matches: wide && query.includes(`min-width: ${RAIL_MIN_WIDTH_PX}px`),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  );
}

/** A stats payload with the fields a test cares about, defaults for the rest. */
export function statsWith(overrides: Partial<Stats>): Stats {
  return { ...STATS, ...overrides };
}
