import { useSyncExternalStore } from "react";

/** The numeral's full display size: 9rem, the size it has always had, and the
 * size it still has wherever there is room for it (DECISIONS.md 9.3). */
export const NUMERAL_MAX_PX = 144;

/** The floor it will not shrink past. Below this the numeral would stop being
 * the dominant element on the page, which is the one thing §17 may not trade
 * away -- so past this point the rails are allowed to reach it instead.
 *
 * 36px is chosen so the floor and the overlap begin at the same width: a
 * nine-digit total is fitted, not floored, down to 856px, and every shorter
 * number far below that. Nothing inside §17.2's swept range (900-1920) is
 * ever floored. */
export const NUMERAL_MIN_PX = 36;

/** The width of the widest digit in the vendored Fraunces, as a fraction of
 * the font size, over the whole range of sizes this fit can produce.
 *
 * Two things measured in Chrome make this one number rather than a table.
 *
 * **The digits are not tabular.** This font ships no `tnum`, so the
 * component's `font-variant-numeric: tabular-nums` is inert and the advances
 * run from 0.372em ("1") to 0.613em ("0"), a 65% spread. The fit cannot use
 * the string on screen anyway: the numeral animates, and a count-up walks
 * through digits nobody chose on its way to the server's value (11.2). A fit
 * computed from the particular frame would resize the numeral mid-count, and
 * one computed from the target alone would be overrun by a wider frame --
 * 412 -> 1000 passes through nothing wider than where it lands, but
 * 999 -> 1111 passes through "1000", 100px wider than "1111". The only bound
 * that holds for every frame is digits x the widest digit, which is "0".
 *
 * **The advance is not proportional to the font size.** Fraunces is variable
 * and carries an optical-size axis, and `font-optical-sizing` defaults to
 * `auto`, so a smaller numeral is set in a wider, sturdier cut of the same
 * face. "0" measures 0.6131em at 144px and 0.66787em at 36px -- 9% wider
 * where there is least room to spare, which is exactly the wrong direction to
 * guess at. The ratio is monotone in size across that range, so the value
 * below is its maximum: measured at the floor, rounded up, and therefore an
 * upper bound at every size in between.
 */
export const DIGIT_ADVANCE_EM = 0.668;

/** The center column's content box: max-w-2xl (42rem) less px-5 twice. The
 * numeral is never allowed wider than this, which is what keeps it centered:
 * a run too wide for its box is not centered in it at all, it starts at the
 * box's left edge and bleeds off the right (DECISIONS.md 17.2). */
export const COLUMN_INK_PX = 632;

/** An open rail, `.rail`'s --rail-expanded. Always the open width, never the
 * collapsed one: the numeral's size does not depend on rail state, so that
 * opening a rail changes nothing whatever about the center (17.1). */
export const RAIL_OPEN_PX = 320;

/** How much daylight the numeral's ink keeps from an open rail. 1rem, the
 * same clearance the old 1456px breakpoint was chosen to leave (17.2). */
export const CLEARANCE_PX = 16;

/**
 * The size the primary numeral renders at, for a viewport this wide and a
 * number this many digits long (DECISIONS.md 17.2).
 *
 * The rails are present at every width and an open one overlays the column,
 * so the thing that has to give is the number. Two constraints, both of them
 * about ink and neither about the element's box:
 *
 *   - it clears both open rails: half of it, plus 320px of rail and 16px of
 *     air, fits in half the viewport
 *   - it fits its own column, so that it stays centered and the first
 *     constraint stays symmetric
 *
 * `digits` is a count, not a string: see DIGIT_ADVANCE_EM for why the fit is
 * deliberately blind to which digits they are.
 */
export function numeralFontSizePx(viewportWidth: number, digits: number): number {
  const available = Math.min(
    COLUMN_INK_PX,
    viewportWidth - 2 * (RAIL_OPEN_PX + CLEARANCE_PX),
  );
  const fits = available / (Math.max(1, digits) * DIGIT_ADVANCE_EM);
  const size = Math.max(NUMERAL_MIN_PX, Math.min(NUMERAL_MAX_PX, fits));
  // Two decimals is far below a pixel at this size, and keeps the style
  // attribute readable. Floored, so the rounding can only add clearance.
  return Math.floor(size * 100) / 100;
}

/** Defensive about the DOM for the same reason motion.ts is: this module is
 * imported by tests that render into jsdom, where an element has no layout
 * and `clientWidth` is 0.
 *
 * `clientWidth` and not `innerWidth` (or a CSS `100vw`) on purpose. Where the
 * browser draws a classic scrollbar rather than an overlay one, it sits
 * inside `innerWidth` but outside both the centered column and the fixed
 * rails -- so `clientWidth` is the only one of the three that measures the
 * space this fit is actually about. */
function snapshot(): number {
  if (typeof document === "undefined" || typeof window === "undefined") return 0;
  return document.documentElement.clientWidth || window.innerWidth || 0;
}

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

/** The numeral's size, re-read whenever the window changes size. A window
 * dragged narrow shrinks the number instead of moving anything. */
export function useNumeralFit(digits: number): number {
  const width = useSyncExternalStore(subscribe, snapshot, () => 0);
  return numeralFontSizePx(width, digits);
}
