import "@testing-library/jest-dom/vitest";

/** jsdom does not implement matchMedia, and every motion-aware component asks
 * it whether to animate. Default to "no preference expressed"; a test that
 * cares calls setReducedMotion() from __tests__/helpers. */
if (typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
