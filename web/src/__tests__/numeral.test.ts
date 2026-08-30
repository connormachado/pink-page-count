import { describe, expect, it } from "vitest";
import {
  CLEARANCE_PX,
  COLUMN_INK_PX,
  DIGIT_ADVANCE_EM,
  NUMERAL_MAX_PX,
  NUMERAL_MIN_PX,
  RAIL_OPEN_PX,
  numeralFontSizePx,
} from "../useNumeralFit";

/** The widest the numeral can draw at this size: every digit as wide as the
 * widest one, because a count-up walks through digits nobody chose. */
function inkWidth(size: number, digits: number): number {
  return size * digits * DIGIT_ADVANCE_EM;
}

/** Ink is centered on the viewport, so its distance from an open rail is the
 * same on both sides. Negative means the rail is over the number. */
function clearance(viewport: number, digits: number): number {
  const size = numeralFontSizePx(viewport, digits);
  return viewport / 2 - inkWidth(size, digits) / 2 - RAIL_OPEN_PX;
}

const WIDTHS: number[] = [];
for (let w = 900; w <= 1920; w++) WIDTHS.push(w);

const DIGITS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

describe("the numeral's fit (DECISIONS.md 17.2)", () => {
  it("clears both open rails at every width from 900 to 1920, for every length", () => {
    const failures = WIDTHS.flatMap((w) =>
      DIGITS.filter((d) => clearance(w, d) < CLEARANCE_PX).map((d) => `${w}px/${d} digits`),
    );
    expect(failures).toEqual([]);
  });

  it("never draws wider than the column it sits in", () => {
    for (const w of WIDTHS) {
      for (const d of DIGITS) {
        expect(inkWidth(numeralFontSizePx(w, d), d)).toBeLessThanOrEqual(COLUMN_INK_PX);
      }
    }
  });

  it("is still 144px wherever the number fits at 144px", () => {
    // Five digits is 42,000 pages a year for a lifetime; six is more than
    // anyone reading this will log. Both are full size on any ordinary window.
    expect(numeralFontSizePx(1440, 5)).toBe(NUMERAL_MAX_PX);
    expect(numeralFontSizePx(1440, 6)).toBe(NUMERAL_MAX_PX);
    expect(numeralFontSizePx(1920, 6)).toBe(NUMERAL_MAX_PX);
    expect(numeralFontSizePx(1200, 5)).toBe(NUMERAL_MAX_PX);
  });

  it("shrinks, rather than overlapping, once the space runs out", () => {
    expect(numeralFontSizePx(900, 9)).toBeLessThan(NUMERAL_MAX_PX);
    expect(numeralFontSizePx(900, 9)).toBeGreaterThan(NUMERAL_MIN_PX);
    expect(numeralFontSizePx(900, 3)).toBeLessThan(numeralFontSizePx(1200, 3));
  });

  it("never goes below the floor, however little room there is", () => {
    for (const w of [0, 320, 500, 672, 700, 900]) {
      for (const d of DIGITS) {
        expect(numeralFontSizePx(w, d)).toBeGreaterThanOrEqual(NUMERAL_MIN_PX);
      }
    }
    // A viewport narrower than two open rails has nothing left to give: the
    // numeral stops at the floor and the rails are allowed to reach it. That
    // is the trade this floor exists to make, and it is only ever made far
    // below the widths §17.2 sweeps (DECISIONS.md 17.2).
    expect(numeralFontSizePx(640, 9)).toBe(NUMERAL_MIN_PX);
    expect(numeralFontSizePx(320, 1)).toBe(NUMERAL_MIN_PX);
    // ...and nothing in the swept range is ever floored, which is why the
    // clearance above holds at 900 for a nine-digit total.
    for (let w = 900; w <= 1920; w += 1) {
      for (const d of DIGITS) expect(numeralFontSizePx(w, d)).toBeGreaterThan(NUMERAL_MIN_PX);
    }
  });

  it("only ever grows with the window", () => {
    for (const d of DIGITS) {
      let previous = 0;
      for (let w = 320; w <= 1920; w += 1) {
        const size = numeralFontSizePx(w, d);
        expect(size).toBeGreaterThanOrEqual(previous);
        previous = size;
      }
    }
  });

  it("is the same size for every string of the same length", () => {
    // The fit takes a count, never the digits themselves: a count-up that
    // passes through 1000 on its way to 1111 must not resize anything (11.2).
    expect(numeralFontSizePx(900, String(1111).length)).toBe(
      numeralFontSizePx(900, String(1000).length),
    );
  });
});
