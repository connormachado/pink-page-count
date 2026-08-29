/** WCAG relative luminance and contrast ratio. Pure functions, no DOM, no
 * dependency -- hand-rolled per DECISIONS.md 13's "no color-picker library,
 * nothing that fetches" rule, which extends to any contrast-checking library
 * too.
 *
 * https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
 */

function parseHex(hex: string): [number, number, number] {
  const clean = hex.trim().replace(/^#/, "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  const value = parseInt(full, 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

function srgbToLinear(channel: number): number {
  const s = channel / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex).map(srgbToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Symmetric: the lighter color is always the numerator. */
export function contrastRatio(hexA: string, hexB: string): number {
  const [lighter, darker] = [relativeLuminance(hexA), relativeLuminance(hexB)].sort(
    (a, b) => b - a,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

/** WCAG AA thresholds. Body text needs 4.5:1; large text (the primary
 * numeral, at display size) needs only 3:1. */
export const MIN_BODY_CONTRAST = 4.5;
export const MIN_LARGE_CONTRAST = 3;
