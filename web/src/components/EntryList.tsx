import type { Class, Entry } from "../types";
import { EntryRow } from "./EntryRow";

type Props = {
  entries: Entry[];
  classes: Class[];
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
};

/** Newest first, exactly as GET /api/entries returns it. The client does not
 * re-sort: DECISIONS.md 4 makes ordering the server's job. */
export function EntryList({ entries, classes, onChanged, onUnreachable }: Props) {
  if (entries.length === 0) {
    return (
      <div className="rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] p-6 text-center">
        <p className="text-[var(--ink)]">Nothing here yet.</p>
        <p className="mt-1 text-sm text-[var(--rose-muted)]">
          Log the pages you read above — one page counts.
        </p>
      </div>
    );
  }

  return (
    <ul aria-label="Reading log" className="flex flex-col gap-3">
      {entries.map((entry) => (
        <EntryRow
          key={entry.id}
          entry={entry}
          classes={classes}
          onChanged={onChanged}
          onUnreachable={onUnreachable}
        />
      ))}
    </ul>
  );
}
