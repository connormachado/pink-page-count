import type { Stats } from "./types";

export type StatKey = "all" | "today" | "streak";

export const CHIPS: ReadonlyArray<{ key: StatKey; label: string }> = [
  { key: "all", label: "All-time" },
  { key: "today", label: "Today" },
  { key: "streak", label: "Streak" },
];

/** Which server number a chip shows, and what to call it.
 *
 * Every value here is read straight off the /api/stats payload. Nothing is
 * derived, combined, or compared -- the server is the only source of truth for
 * a displayed number, and DECISIONS.md 8 rules out comparisons anyway.
 */
export function selectStat(stats: Stats, key: StatKey): { value: number; label: string } {
  switch (key) {
    case "today":
      return { value: stats.pages_today, label: "pages today" };
    case "streak":
      return {
        value: stats.current_streak_days,
        label: stats.current_streak_days === 1 ? "day in a row" : "days in a row",
      };
    case "all":
    default:
      return { value: stats.pages_all_time, label: "pages, all time" };
  }
}
