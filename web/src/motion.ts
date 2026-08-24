/** Shared motion helpers. No animation library -- rAF and CSS only.
 *
 * Every animation in this app is gated on prefers-reduced-motion, and every
 * looping animation stops when the tab is hidden. She reads on battery in a
 * library; a page in a background tab must not be spending her power on
 * confetti nobody is looking at.
 */

/** True when the reader has asked for less motion. Defensive about matchMedia
 * because jsdom does not implement it. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Read a duration token off the document, so DECISIONS.md 9.2 stays the single
 * source for how long things take. Accepts "900ms" or "0.9s". */
export function durationToken(name: string, fallbackMs: number): number {
  if (typeof window === "undefined" || typeof getComputedStyle !== "function") {
    return fallbackMs;
  }
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (raw.endsWith("ms")) return Number.parseFloat(raw) || fallbackMs;
  if (raw.endsWith("s")) return (Number.parseFloat(raw) || fallbackMs / 1000) * 1000;
  return fallbackMs;
}
