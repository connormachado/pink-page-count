/** The class swatches, by token name.
 *
 * The VALUES live in web/src/tokens.css and nowhere else in this repo
 * (DECISIONS.md 9, 12.2) -- this module names the tokens and reads them back at
 * runtime, so no hex literal appears here either. The server has no palette at
 * all; whatever this resolves is sent explicitly on create.
 */
export const CLASS_TOKENS = [
  "--class-rose",
  "--class-berry",
  "--class-plum",
  "--class-lilac",
  "--class-coral",
  "--class-peach",
  "--class-moss",
  "--class-sky",
  "--class-sunflower",
  "--class-butter",
  "--class-azure",
  "--class-teal",
  "--class-lavender",
  "--class-piggy",
] as const;

/** The resolved palette, in token order. Empty if the stylesheet has not loaded. */
export function paletteColors(): string[] {
  const styles = getComputedStyle(document.documentElement);
  return CLASS_TOKENS.map((token) => styles.getPropertyValue(token).trim()).filter(
    (value) => value !== "",
  );
}

/** The color to pre-select for a new class: the first one not already in use,
 * wrapping by count once all of them are taken.
 *
 * `used` is the colors of the non-archived classes -- an archived class has put
 * its color back. Returns null when the palette could not be resolved, in which
 * case the caller sends no color and the server's fallback applies (12.2). */
export function suggestColor(used: string[], liveCount: number): string | null {
  const palette = paletteColors();
  if (palette.length === 0) return null;

  const taken = new Set(used.map((color) => color.toLowerCase()));
  const free = palette.find((color) => !taken.has(color.toLowerCase()));
  return free ?? palette[liveCount % palette.length];
}
