import { useCountUp } from "../useCountUp";

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
 */
export function BigNumber({ value, label, countToken }: Props) {
  const displayed = useCountUp(value, countToken);

  return (
    <div className="text-center">
      <div
        data-testid="big-number"
        aria-hidden="true"
        className="font-[family-name:var(--font-number)] text-[var(--pink-hot)] leading-none
                   text-[7rem] sm:text-[9rem] font-semibold tabular-nums"
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
