/** Mirrors app/models.py::EntryOut. `pages` is computed by the server on every
 * read and is never sent back (DECISIONS.md 1.1). */
export type Entry = {
  id: string;
  page_start: number;
  page_end: number;
  pages: number;
  read_at: string;
  note: string | null;
  created_at: string;
  updated_at: string;
};

/** Mirrors app/models.py::StatsOut.
 *
 * There is no longest_streak_days here because the API does not return one.
 * DECISIONS.md 8: a field absent from the payload cannot be rendered next to
 * current_streak_days. Do not add it to this type. */
export type Stats = {
  pages_today: number;
  pages_all_time: number;
  current_streak_days: number;
  entry_count: number;
  first_entry_date: string | null;
};

export type EntryCreate = {
  page_start: number;
  page_end: number;
  note?: string | null;
  read_at?: string;
};

/** PATCH sends only the fields that actually changed. */
export type EntryPatch = Partial<EntryCreate>;
