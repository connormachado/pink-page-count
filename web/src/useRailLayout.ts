import { useSyncExternalStore } from "react";

/** The viewport width at or above which Settings and Classes move out of the
 * center column and into the two edge rails (DECISIONS.md 17).
 *
 * Not a taste value. It is set by the widest thing the app can draw: a
 * 9-digit all-time total. At the numeral's 144px display size that run of
 * digits is 704px of ink, inside a column whose content box is only 632px,
 * and an over-wide centered text run overflows to one side, not two -- in
 * LTR it starts at the content box's left edge and bleeds 72px past its
 * right. So the numeral's ink sits far closer to the right rail than to the
 * left, and the right rail is the only one that can ever reach it.
 *
 * Measured in Chrome, both rails open, ink taken from the text run's own
 * rect rather than the element's:
 *
 *   ink.right = (W - 672) / 2 + 20 + 704.09      right rail edge = W - 320
 *   clearance(W) = W / 2 - 708.09
 *
 * which is negative -- an actual overlap -- for every width below 1417, and
 * clears a full 1rem at 1456. 1456 is that width rounded to the 16px grid:
 * 20px of clearance to the numeral's ink and 72px to the column box, at the
 * narrowest width where rails exist at all.
 *
 * Below this the panels stack under the entry log exactly as they did
 * before. Measured in Chrome, not reasoned about -- see DECISIONS.md 17. */
export const RAIL_MIN_WIDTH_PX = 1456;

const RAIL_MEDIA_QUERY = `(min-width: ${RAIL_MIN_WIDTH_PX}px)`;

/** Defensive about matchMedia for the same reason motion.ts is: jsdom does
 * not implement it, and a missing implementation means "not wide", which is
 * the stacked layout this app had before rails existed. */
function query(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(RAIL_MEDIA_QUERY);
}

function subscribe(onChange: () => void): () => void {
  const list = query();
  if (list === null || typeof list.addEventListener !== "function") return () => {};
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

function snapshot(): boolean {
  return query()?.matches ?? false;
}

/** True when the window is wide enough for the rails. Re-renders on resize
 * across the breakpoint, so a window dragged narrow puts the panels back
 * under the entry log without a reload. */
export function useRailLayout(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
