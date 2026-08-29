/** The theme system: preset ids, the semantic tokens a custom theme may
 * override, and the functions that apply/read/cache a theme. See
 * DECISIONS.md 13.
 *
 * No hex literal appears here. Preset colors are frontend-only data (the
 * server only validates ids -- it has no palette, mirroring 12.2's "the
 * server has no palette" for classes), but they still live in tokens.css
 * exclusively -- this module names presets by id and label only.
 */

export type ThemeId = "pink" | "jewel" | "neutral" | "cool" | "contrast" | "midnight";
export const CUSTOM_THEME_ID = "custom";

export const DEFAULT_THEME: ThemeId = "pink";

/** The six semantic tokens a custom theme may override, spelled as the
 * literal CSS custom-property names -- not a snake_case shadow encoding.
 * Must match app/settings.py::SEMANTIC_TOKENS exactly. */
export const SEMANTIC_TOKENS = [
  "--pink-hot",
  "--pink-wash",
  "--pink-surface",
  "--pink-edge",
  "--ink",
  "--rose-muted",
] as const;

export type SemanticToken = (typeof SEMANTIC_TOKENS)[number];

export type CustomTheme = Partial<Record<SemanticToken, string>>;

/** Must match app/settings.py::THEME_IDS exactly -- the backend has no
 * colors, only ids, and 422s on anything not in this set (or "custom"). */
export const PRESETS: ReadonlyArray<{ id: ThemeId; label: string }> = [
  { id: "pink", label: "Pink" },
  { id: "jewel", label: "Jewel" },
  { id: "neutral", label: "Sand" },
  { id: "cool", label: "Slate" },
  { id: "contrast", label: "High contrast" },
  { id: "midnight", label: "Midnight" },
];

/** Human-friendly labels for the theme editor's color inputs. */
export const TOKEN_LABELS: Record<SemanticToken, string> = {
  "--pink-hot": "Primary number",
  "--pink-wash": "Page background",
  "--pink-surface": "Card surface",
  "--pink-edge": "Borders & chips",
  "--ink": "Main text",
  "--rose-muted": "Secondary text",
};

/** localStorage key for the first-paint cache. PAINT CACHE ONLY -- never a
 * data source. Mirrored, necessarily as a literal string, in the inline
 * boot script in web/index.html; keep the two in sync (DECISIONS.md 13). */
export const PAINT_CACHE_KEY = "ppc:theme-cache";

type PaintCache = { theme: ThemeId | typeof CUSTOM_THEME_ID; custom_theme: CustomTheme | null };

/** Set data-theme on the root and reconcile inline overrides: apply every
 * token present in customTheme, and clear (removeProperty) every semantic
 * token NOT present, so a stale override from a previous custom theme never
 * lingers past a real settings fetch. */
export function applyTheme(
  theme: ThemeId | typeof CUSTOM_THEME_ID,
  customTheme: CustomTheme | null,
): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme === CUSTOM_THEME_ID ? DEFAULT_THEME : theme);

  for (const token of SEMANTIC_TOKENS) {
    const value = customTheme?.[token];
    if (typeof value === "string" && value) {
      root.style.setProperty(token, value);
    } else {
      root.style.removeProperty(token);
    }
  }
}

/** The resolved value of every semantic token, read off the live cascade --
 * exactly like palette.ts reads the --class-* tokens. No hex literal here. */
export function readResolvedTheme(): Record<SemanticToken, string> {
  const styles = getComputedStyle(document.documentElement);
  const result = {} as Record<SemanticToken, string>;
  for (const token of SEMANTIC_TOKENS) {
    result[token] = styles.getPropertyValue(token).trim();
  }
  return result;
}

/** Mirror the resolved theme into localStorage as a paint cache only. A
 * cleared cache must lose nothing -- settings.json remains the sole source
 * of truth (DECISIONS.md 13). */
export function writePaintCache(cache: PaintCache): void {
  try {
    localStorage.setItem(PAINT_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Storage disabled or full: the paint cache is an optimization, not a
    // requirement, so a failure here is silently ignored.
  }
}
