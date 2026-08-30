import { useCountUp } from "../useCountUp";
import { useNumeralFit } from "../useNumeralFit";

type Props = {
  value: number;
  label: string;
  /** Changes only on a successful save. Any other change to `value` -- a chip,
   * a refetch -- lands instantly. */
  countToken: number;
};

/** The dominant element on the page.
 *
 * The only element in the app allowed to use --pink-hot (DECISIONS.md 9.1).
 *
 * Two nodes, on purpose. The visible numeral animates and is aria-hidden, so a
 * screen reader is not read forty intermediate frames of a count-up. The live
 * region beside it is text-only and carries the final server value, so the
 * change is announced exactly once.
 *
 * Its size is the one thing here that is not fixed: the rails are present at
 * every width and an open one overlays this column, so the numeral is fitted
 * to the space between them rather than reflowing anything (DECISIONS.md
 * 17.2). It is still the largest element on the page at every width, and at
 * every width where it fits it is still 144px.
 */
export function BigNumber({ value, label, countToken }: Props) {
  const displayed = useCountUp(value, countToken);

  // The wider of what is on screen and where it is going. Taking the target
  // into account is what keeps the size still through a count-up; taking the
  // displayed value into account covers the overshoot, which can briefly
  // carry a digit past the number it settles on (11.2).
  const digits = Math.max(String(displayed).length, String(value).length);
  const fontSize = useNumeralFit(digits);

  return (
    <div className="text-center">
      <div
        data-testid="big-number"
        aria-hidden="true"
        style={{ fontSize: `${fontSize}px` }}
        className="font-[family-name:var(--font-number)] text-[var(--pink-hot)] leading-none
                   font-semibold tabular-nums"
      >
        {displayed}
      </div>
      <p aria-hidden="true" className="mt-2 text-[var(--rose-muted)] text-sm tracking-wide">
        {label}
      </p>
      <p data-testid="big-number-announcement" aria-live="polite" aria-atomic="true" className="sr-only">
        {value} {label}
      </p>
    </div>
  );
}
