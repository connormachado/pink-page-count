import { describe, expect, it } from "vitest";
import { contrastRatio, MIN_BODY_CONTRAST, MIN_LARGE_CONTRAST, relativeLuminance } from "../contrast";
import { ATTRIBUTION_TOKEN } from "../components/DailyQuote";
import { PRESETS } from "../theme";
// Vite's ?raw import returns the file's real text content. This project's
// vitest config otherwise stubs every CSS-extension import (including a
// `?raw` query) to an empty string (test.css: false, by default) -- so
// vite.config.ts carves out an explicit include for tokens.css specifically,
// letting this one file's content through unstubbed. This test therefore
// checks the actual shipped file, never a fixture that could drift from it.
// @ts-expect-error -- no type declaration for ?raw imports, and none is needed here.
import tokensCss from "../tokens.css?raw";

describe("relativeLuminance", () => {
  it("is 1 for white and 0 for black", () => {
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 5);
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 5);
  });
});

describe("contrastRatio", () => {
  it("is symmetric", () => {
    expect(contrastRatio("#ff2e88", "#fff5f8")).toBeCloseTo(
      contrastRatio("#fff5f8", "#ff2e88"),
      10,
    );
  });

  it("is 21 for pure black on pure white", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
  });
});

/** Pull a [data-theme="id"] block's --theme-* declarations out of the real
 * tokens.css text. Test-support only; never shipped, so "a hex literal
 * appears in tokens.css and nowhere else" stays literally true. */
function themeBlock(css: string, id: string): Record<string, string> {
  const match = css.match(
    new RegExp(`\\[data-theme=["']${id}["']\\][^{]*\\{([^}]*)\\}`),
  );
  const isDefault = id === "pink" && !match;
  const body = match
    ? match[1]
    : (() => {
        const rootMatch = css.match(/:root,\s*\[data-theme="pink"\]\s*\{([^}]*)\}/);
        if (!rootMatch) throw new Error(`No theme block found for "${id}"`);
        return rootMatch[1];
      })();
  if (!match && !isDefault) throw new Error(`No theme block found for "${id}"`);

  const tokens: Record<string, string> = {};
  for (const line of body.split(";")) {
    const [name, value] = line.split(":").map((part) => part?.trim());
    if (name && value && name.startsWith("--theme-")) tokens[name] = value;
  }
  return tokens;
}

describe.each(PRESETS)("preset $id", ({ id }) => {
  const t = themeBlock(tokensCss, id);

  it("body text on the card surface clears 4.5:1", () => {
    expect(contrastRatio(t["--theme-ink"], t["--theme-surface"])).toBeGreaterThanOrEqual(
      MIN_BODY_CONTRAST,
    );
  });

  it("secondary text clears 4.5:1 on both backgrounds", () => {
    expect(
      contrastRatio(t["--theme-rose-muted"], t["--theme-surface"]),
    ).toBeGreaterThanOrEqual(MIN_BODY_CONTRAST);
    expect(contrastRatio(t["--theme-rose-muted"], t["--theme-wash"])).toBeGreaterThanOrEqual(
      MIN_BODY_CONTRAST,
    );
  });

  it("the quote attribution clears 4.5:1 on both backgrounds", () => {
    // DECISIONS.md 10.1 (amended). Lower-emphasis text is where a contrast
    // regression hides, so the attribution is checked by name and at the BODY
    // threshold, not the large-text one -- it is 14px.
    //
    // It resolves to --rose-muted today, which the test above already covers.
    // That is the point: the de-emphasis is size and alignment, never a dimmer
    // color, and §9 has no dimmer token to reach for. If someone ever gives
    // the attribution a color of its own, ATTRIBUTION_TOKEN changes and this
    // check follows it there.
    const token = `--theme${ATTRIBUTION_TOKEN.slice(1)}`;
    expect(t[token]).toBeDefined();
    expect(contrastRatio(t[token], t["--theme-wash"])).toBeGreaterThanOrEqual(
      MIN_BODY_CONTRAST,
    );
    expect(contrastRatio(t[token], t["--theme-surface"])).toBeGreaterThanOrEqual(
      MIN_BODY_CONTRAST,
    );
  });

  it("the primary number is legible at display size", () => {
    expect(contrastRatio(t["--theme-hot"], t["--theme-wash"])).toBeGreaterThanOrEqual(
      MIN_LARGE_CONTRAST,
    );
  });
});
