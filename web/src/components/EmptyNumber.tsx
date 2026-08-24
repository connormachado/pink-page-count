/** What stands where the number goes before there is anything to count.
 *
 * Rendered only when stats.entry_count === 0 -- never when a displayed value
 * happens to be zero. A Today of 0 at 7am is an ordinary morning and still
 * shows a 0; a big pink "0" on the very first run is not a stat, it is a
 * verdict on someone who hasn't started yet (DECISIONS.md 8).
 */
export function EmptyNumber() {
  return (
    <div className="text-center">
      <p className="font-[family-name:var(--font-number)] text-[var(--ink)] text-3xl sm:text-4xl leading-snug">
        Your first pages go here.
      </p>
      <p className="mt-3 text-[var(--rose-muted)]">
        Put in where you started and where you stopped. Any two numbers at all.
      </p>
    </div>
  );
}
