/** Preview arithmetic for the entry form, and nothing else.
 *
 * This is the one place the client is allowed to do page math, and it is a
 * preview of an unsaved input -- it touches no server data and is never sent.
 * Page counting is INCLUSIVE: 43-71 is 29 pages, 43-43 is 1 page
 * (DECISIONS.md 1.1). Every *saved* number on screen comes from the server.
 */
export function previewPages(start: number, end: number): number {
  return end - start + 1;
}

/** The text under the inputs, or null when there is nothing sensible to show
 * yet. Returns null rather than a complaint: an unfinished input is not a
 * mistake (DECISIONS.md 8). */
export function previewLine(startRaw: string, endRaw: string): string | null {
  const start = parsePage(startRaw);
  const end = parsePage(endRaw);
  if (start === null || end === null || end < start) return null;
  return `that's ${plural(previewPages(start, end), "page")}`;
}

/** Strict: "12abc", "1.5", "" and "-3" are all not-a-page. */
export function parsePage(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  return Number(trimmed);
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
