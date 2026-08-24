import { useCallback, useEffect, useState } from "react";
import { ServerUnreachable, api } from "./api";
import { BigNumber } from "./components/BigNumber";
import { Chips } from "./components/Chips";
import { EntryForm } from "./components/EntryForm";
import { EntryList } from "./components/EntryList";
import { selectStat, type StatKey } from "./stat";
import type { Entry, Stats } from "./types";

/** Phase 2 keeps this a constant. Phase 3 gives it somewhere to come from. */
const MESSAGE = "Every page you read is one you didn't have before.";

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [selected, setSelected] = useState<StatKey>("all");

  /** The only way anything on this page changes.
   *
   * After every successful create, edit, or delete we refetch both endpoints
   * and render what comes back. No displayed total is ever adjusted by
   * arithmetic here, and no running count is kept in state -- the server is
   * the only source of truth for a displayed number. */
  const refresh = useCallback(async () => {
    try {
      const [nextStats, nextEntries] = await Promise.all([api.stats(), api.entries()]);
      setStats(nextStats);
      setEntries(nextEntries);
      setUnreachable(false);
    } catch (error) {
      if (error instanceof ServerUnreachable) setUnreachable(true);
      else throw error;
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Nobody answered. Say so plainly and say how to fix it -- showing a zero
  // here would be a lie that looks like data.
  if (unreachable) {
    return (
      <Shell>
        <div className="rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] p-6 text-center">
          <p className="text-[var(--ink)]">The reading tracker isn't running right now.</p>
          <p className="mt-2 text-sm text-[var(--rose-muted)]">
            Start it by double-clicking <code>run.command</code> in the project folder, then
            reload this page. Nothing you've logged has gone anywhere.
          </p>
          <button
            type="button"
            onClick={() => void refresh()}
            className="mt-4 rounded-full border border-[var(--pink-edge)] bg-[var(--pink-edge)]
                       px-5 py-2 text-[var(--ink)] transition-colors duration-[var(--dur-ui)]
                       cursor-pointer hover:bg-[var(--pink-surface)]"
          >
            Try again
          </button>
        </div>
      </Shell>
    );
  }

  if (stats === null || entries === null) {
    return (
      <Shell>
        <p className="text-center text-sm text-[var(--rose-muted)]">Loading…</p>
      </Shell>
    );
  }

  const { value, label } = selectStat(stats, selected);

  return (
    <Shell>
      <p className="text-center text-[var(--rose-muted)]">{MESSAGE}</p>

      <BigNumber value={value} label={label} />

      <Chips selected={selected} onSelect={setSelected} />

      <EntryForm onSaved={refresh} onUnreachable={() => setUnreachable(true)} />

      <EntryList
        entries={entries}
        onChanged={refresh}
        onUnreachable={() => setUnreachable(true)}
      />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-5 py-10 sm:py-14">
      {children}
    </main>
  );
}
