type Props = {
  value: number;
  label: string;
};

/** The dominant element on the page.
 *
 * The only element in the app allowed to use --pink-hot (DECISIONS.md 9.1).
 * Wrapped in a polite live region so switching a chip or saving an entry is
 * announced to a screen reader without interrupting it.
 */
export function BigNumber({ value, label }: Props) {
  return (
    <div aria-live="polite" aria-atomic="true" className="text-center">
      <div
        data-testid="big-number"
        className="font-[family-name:var(--font-number)] text-[var(--pink-hot)] leading-none
                   text-[7rem] sm:text-[9rem] font-semibold tabular-nums"
      >
        {value}
      </div>
      <p className="mt-2 text-[var(--rose-muted)] text-sm tracking-wide">{label}</p>
    </div>
  );
}
