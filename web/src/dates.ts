/** Display and form helpers for `read_at`.
 *
 * No day-boundary math lives here. DECISIONS.md 2.3 puts the 4am->4am rule in
 * exactly one function, app/daytime.py::day_key, and there is no second
 * implementation anywhere -- including this file. The client formats
 * timestamps; the server decides which day they belong to.
 */

const pad = (n: number) => String(n).padStart(2, "0");

/** "Mon, Aug 24" for this year, "Aug 24, 2025" for any other. */
export function formatReadAt(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const sameYear = when.getFullYear() === new Date().getFullYear();
  return when.toLocaleDateString(undefined, {
    weekday: sameYear ? "short" : undefined,
    month: "short",
    day: "numeric",
    year: sameYear ? undefined : "numeric",
  });
}

/** The local calendar date of a stored timestamp, as <input type="date"> wants it. */
export function toDateInput(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

/** Move a timestamp to another calendar day, keeping its time of day.
 *
 * Sent without an offset on purpose: DECISIONS.md 2.2 says the server reads a
 * naive read_at as local time and stores it normalized with the local offset.
 */
export function moveToDate(iso: string, dateInput: string): string {
  const when = new Date(iso);
  const time = Number.isNaN(when.getTime())
    ? "12:00:00"
    : `${pad(when.getHours())}:${pad(when.getMinutes())}:${pad(when.getSeconds())}`;
  return `${dateInput}T${time}`;
}
