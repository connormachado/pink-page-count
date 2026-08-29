import type { DailyQuote as Quote } from "../types";

/** The one color token the attribution uses, named so the WCAG check in
 * contrast.test.ts can assert against the attribution's actual color rather
 * than against a token that merely happens to match it today.
 *
 * Tailwind's scanner needs the literal in the className below, so this is a
 * parallel declaration -- quote.test.tsx asserts the two agree. */
export const ATTRIBUTION_TOKEN = "--rose-muted";

/** The quote at the top of the page, and -- only when there is one -- who said
 * it (DECISIONS.md 10.1, amended).
 *
 * The attributor is right-aligned to this block, one step smaller than the
 * quote, and carries --rose-muted: the same secondary-text token the quote
 * itself uses. That is deliberate. It is the only semantic token in §9 that is
 * checked at the 4.5:1 body threshold against both backgrounds, so the
 * de-emphasis here is size and alignment, never a dimmer color. A washed-out
 * variant is exactly where a contrast regression would hide, and there is no
 * token for one -- §9's palette is six names and this component invents none.
 *
 * When `attribution` is null NOTHING is rendered: no em dash, no empty
 * element, no margin. The single-line case is byte-for-byte the markup that
 * shipped before this feature, so its height is unchanged. */
export function DailyQuote({ quote }: { quote: Quote }) {
  return (
    <div data-testid="quote-block">
      <p className="text-center text-[var(--rose-muted)]">{quote.text}</p>
      {quote.attribution === null ? null : (
        <p
          data-testid="quote-attribution"
          className="mt-1 text-right text-sm text-[var(--rose-muted)]"
        >
          {`— ${quote.attribution}`}
        </p>
      )}
    </div>
  );
}
