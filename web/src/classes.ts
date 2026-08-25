import type { Class, Entry } from "./types";

/** The class an entry belongs to, or undefined.
 *
 * A class_id naming a class that is not in the list is undefined here, not an
 * error: DECISIONS.md 1.3 says a dangling reference loads fine and renders as
 * no class. */
export function findClass(classes: Class[], id: string | null): Class | undefined {
  if (id === null) return undefined;
  return classes.find((item) => item.id === id);
}

/** What the picker offers.
 *
 * Archived classes vanish from the picker but stay valid on existing entries,
 * so `keep` re-admits the one an entry already carries -- editing an old entry
 * can never silently strip its class (DECISIONS.md 12.4). */
export function pickableClasses(classes: Class[], keep?: string | null): Class[] {
  return classes.filter(
    (item) => !item.archived || (keep != null && item.id === keep),
  );
}

/** The default selection on the entry form: the class of the newest entry.
 *
 * Entries arrive newest-first from the server (DECISIONS.md 4), so that is
 * entries[0] -- no sorting and no arithmetic happens here. If the newest entry
 * has no class, or names an archived or missing one, the default is "no class".
 *
 * The picker mirrors exactly what she did last time, which is why this looks at
 * one entry rather than searching back for the last *classified* one: that
 * would make a deliberate "no class" impossible to keep (DECISIONS.md 12.4). */
export function defaultClassId(entries: Entry[], classes: Class[]): string | null {
  const newest = entries[0];
  if (!newest || newest.class_id === null) return null;
  const subject = findClass(classes, newest.class_id);
  if (subject === undefined || subject.archived) return null;
  return subject.id;
}
