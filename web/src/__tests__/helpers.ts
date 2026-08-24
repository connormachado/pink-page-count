import { vi } from "vitest";
import type { Entry, Stats } from "../types";

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
  created_at: "2026-08-24T21:12:03-04:00",
  updated_at: "2026-08-24T21:12:03-04:00",
};

type Route = { status?: number; body?: unknown };

/** Stub fetch. No test in this file ever talks to a live backend. */
export function stubFetch(routes: {
  stats?: Route;
  entries?: Route;
  post?: Route;
  patch?: Route;
  delete?: Route;
}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    let route: Route | undefined;
    if (method === "POST") route = routes.post;
    else if (method === "PATCH") route = routes.patch;
    else if (method === "DELETE") route = routes.delete ?? { status: 204 };
    else if (url.includes("/api/stats")) route = routes.stats ?? { body: STATS };
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
