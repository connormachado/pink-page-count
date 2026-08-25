import type { Class } from "../types";

/** The colored dot beside a class name.
 *
 * aria-hidden and decorative: the title is always rendered next to it, so color
 * is never the only thing carrying the meaning. The color is a value the server
 * sent, flowing into a style attribute -- not a literal in this file
 * (DECISIONS.md 12.2). */
export function ClassDot({ subject }: { subject: Class | undefined }) {
  if (subject === undefined) return null;
  return (
    <span
      aria-hidden="true"
      style={{ backgroundColor: subject.color }}
      className="inline-block size-2.5 shrink-0 rounded-full"
    />
  );
}
