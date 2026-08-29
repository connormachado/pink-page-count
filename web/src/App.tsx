import { useCallback, useEffect, useRef, useState } from "react";
import { ServerUnreachable, api } from "./api";
import { BigNumber } from "./components/BigNumber";
import { Celebration } from "./components/Celebration";
import { Chips } from "./components/Chips";
import { DailyQuote } from "./components/DailyQuote";
import { EmptyNumber } from "./components/EmptyNumber";
import { EntryForm } from "./components/EntryForm";
import { ClassManager } from "./components/ClassManager";
import { EntryList } from "./components/EntryList";
import { Rail, type PanelChrome } from "./components/Rail";
import { SaveConfirmation } from "./components/SaveConfirmation";
import { SettingsPanel } from "./components/SettingsPanel";
import { crossedMilestone } from "./milestones";
import { FALLBACK_QUOTE, fetchQuote } from "./quote";
import { chipFromSetting, selectStat, type StatKey } from "./stat";
import { applyTheme, readResolvedTheme, writePaintCache, type SemanticToken } from "./theme";
import { useRailLayout } from "./useRailLayout";
import type { Class, Entry, Settings, Stats } from "./types";

/** What a refresh was caused by. Only "save" -- a brand new entry -- may count
 * up or celebrate. An edit or a delete refetches exactly the same way and shows
 * nothing, which is how a delete that drops the total back under a threshold
 * stays silent (DECISIONS.md 11). */
type Cause = "load" | "save" | "change";

const CONFIRMATIONS = ["Saved.", "Got it.", "Logged.", "Added."];

/** How long the confirmation and the celebration stay before clearing. */
const CONFIRM_MS = 2600;
const CELEBRATE_MS = 5200;

/** How often this page tells the server it is still open (DECISIONS.md 16.2).
 * The server gives up after five minutes, so this is ten beats of margin --
 * enough that Chrome's most aggressive background-tab throttling, which slows
 * a hidden tab's timers to once a minute, still lands five beats inside it. */
const HEARTBEAT_MS = 30_000;

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [classes, setClasses] = useState<Class[] | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [resolvedTheme, setResolvedTheme] = useState<Record<SemanticToken, string> | null>(
    null,
  );
  const [unreachable, setUnreachable] = useState(false);
  const [selected, setSelected] = useState<StatKey>("all");
  const [quote, setQuote] = useState(FALLBACK_QUOTE);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [milestone, setMilestone] = useState<number | null>(null);

  /** Whether the window is wide enough for the two edge rails, and whether
   * each one is open. Purely where she is looking right now: none of it is
   * sent to the server or written to settings.json, and a reload starts with
   * both rails shut again (DECISIONS.md 17). */
  const railed = useRailLayout();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [classesOpen, setClassesOpen] = useState(false);

  /** Bumped on a successful save. BigNumber counts up when it changes and
   * lands instantly on every other kind of change. */
  const [countToken, setCountToken] = useState(0);

  /** The all-time total we last saw from the server, for the milestone
   * comparison. A ref, seeded to null, and never persisted anywhere: that is
   * what makes celebrating stateless. A page reload starts it at null again, so
   * a reload cannot re-fire something that already happened. */
  const previousAllTime = useRef<number | null>(null);

  /** The only way anything on this page changes.
   *
   * After every successful create, edit, or delete we refetch both endpoints
   * and render what comes back. No displayed total is ever adjusted by
   * arithmetic here, and no running count is kept in state -- the server is
   * the only source of truth for a displayed number. The count-up animates
   * toward what arrives below; it never produces it. */
  const refresh = useCallback(async (cause: Cause = "load") => {
    try {
      const [nextStats, nextEntries, nextClasses, nextSettings] = await Promise.all([
        api.stats(),
        api.entries(),
        api.classes(),
        api.settings(),
      ]);

      if (cause === "save") {
        const before = previousAllTime.current;
        setCountToken((token) => token + 1);
        setConfirmation(CONFIRMATIONS[Math.floor(Math.random() * CONFIRMATIONS.length)]);
        // Compare the total from before this save to the one the server just
        // returned. Both numbers came from the server; nothing is derived.
        if (before !== null) {
          setMilestone(crossedMilestone(before, nextStats.pages_all_time));
        }
      }

      previousAllTime.current = nextStats.pages_all_time;
      setStats(nextStats);
      setEntries(nextEntries);
      setClasses(nextClasses);
      setSettings(nextSettings);
      // Only on load: picking a chip during a session never rewrites the
      // setting, and a save/change refresh must not yank the view out from
      // under whatever she's currently looking at (DECISIONS.md 13).
      if (cause === "load") setSelected(chipFromSetting(nextSettings.default_chip));
      setUnreachable(false);
    } catch (error) {
      if (error instanceof ServerUnreachable) setUnreachable(true);
      else throw error;
    }
  }, []);

  useEffect(() => {
    void refresh("load");
    void fetchQuote().then(setQuote);
  }, [refresh]);

  // The app is alive for exactly as long as this page is open (DECISIONS.md
  // 16.2). There is no Dock icon and no menu bar to quit from, so this tab is
  // the window: while it exists it says so, and when it goes the server goes.
  //
  // Deliberately no `document.visibilityState` check anywhere in here. A tab
  // in a background window, or behind twenty others, is still a tab she has
  // open -- only closing it, or quitting the browser, may end the app.
  //
  // Failures are swallowed on purpose. A missed beat is not worth a word: the
  // server either comes back before the timeout or it has already gone, and in
  // neither case is a keepalive the thing that should say so. It must never
  // reach setUnreachable -- a blip here would replace a page full of her
  // reading with an error she cannot act on.
  useEffect(() => {
    const beat = () => void api.heartbeat().catch(() => {});
    beat();
    const timer = window.setInterval(beat, HEARTBEAT_MS);
    return () => window.clearInterval(timer);
  }, []);

  // Applies on every settings fetch, load and later changes alike.
  // settings.json is the sole source of truth (DECISIONS.md 13) -- this
  // effect is what makes that true on screen: it sets data-theme and any
  // custom overrides, clears overrides that are no longer present, mirrors
  // the result into the paint cache, and reads the resolved colors back
  // (synchronously, right after applying them, so there is no race against
  // a child reading stale values) for the theme editor's color inputs.
  useEffect(() => {
    if (settings === null) return;
    const theme = settings.theme as Parameters<typeof applyTheme>[0];
    applyTheme(theme, settings.custom_theme);
    writePaintCache({ theme, custom_theme: settings.custom_theme });
    setResolvedTheme(readResolvedTheme());
  }, [settings]);

  // Both of these clear themselves. Nothing on this page waits to be dismissed.
  useEffect(() => {
    if (confirmation === null) return;
    const timer = window.setTimeout(() => setConfirmation(null), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [confirmation]);

  useEffect(() => {
    if (milestone === null) return;
    const timer = window.setTimeout(() => setMilestone(null), CELEBRATE_MS);
    return () => window.clearTimeout(timer);
  }, [milestone]);

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
            onClick={() => void refresh("load")}
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

  if (stats === null || entries === null || classes === null || settings === null) {
    return (
      <Shell>
        <p className="text-center text-sm text-[var(--rose-muted)]">Loading…</p>
      </Shell>
    );
  }

  const { value, label } = selectStat(stats, selected);

  // Conditioned on entry_count, never on the displayed value. A Today of 0 at
  // 7am is an ordinary morning and still renders a 0 (DECISIONS.md 11).
  const nothingLoggedYet = stats.entry_count === 0;

  // The same two panels, in whichever frame the window is wide enough for.
  // One instance of each is mounted at a time -- a rail and a stacked card
  // are two chromes around one body, never two copies of it (DECISIONS.md
  // 17). A class or settings change is an ordinary "change" refresh in both:
  // it never counts up and never celebrates (11.2, 12.4, 13).
  const classManager = (chrome: PanelChrome) => (
    <ClassManager
      chrome={chrome}
      classes={classes}
      onChanged={() => refresh("change")}
      onUnreachable={() => setUnreachable(true)}
    />
  );

  const settingsPanel = (chrome: PanelChrome) => (
    <SettingsPanel
      chrome={chrome}
      settings={settings}
      resolvedTheme={resolvedTheme}
      onChanged={() => refresh("change")}
      onUnreachable={() => setUnreachable(true)}
    />
  );

  return (
    <>
      <Shell>
        <DailyQuote quote={quote} />

        {nothingLoggedYet ? (
          <EmptyNumber />
        ) : (
          <>
            <BigNumber value={value} label={label} countToken={countToken} />
            <Chips selected={selected} onSelect={setSelected} />
          </>
        )}

        <SaveConfirmation message={confirmation} />
        <Celebration milestone={milestone} />

        <EntryForm
          onSaved={() => refresh("save")}
          onUnreachable={() => setUnreachable(true)}
          classes={classes}
          entries={entries}
        />

        <EntryList
          entries={entries}
          classes={classes}
          onChanged={() => refresh("change")}
          onUnreachable={() => setUnreachable(true)}
        />

        {/* Narrow windows only: the two panels stack under the entry log,
            exactly where they lived before the rails existed. Above the
            breakpoint they are rendered below instead, and nothing here is
            mounted (DECISIONS.md 17). */}
        {railed ? null : (
          <>
            {classManager("details")}
            {settingsPanel("details")}
          </>
        )}

        {/* A backup, not a feature: a plain link, no fetch/blob JS. The browser
            triggers the download itself from the Content-Disposition header the
            server sends back (DECISIONS.md 4.4). It is not Settings and it is
            not Classes, so the rails left it where it was: last, and out of
            the way. */}
        <a
          href="/api/export"
          className="text-center text-sm text-[var(--rose-muted)] underline
                     underline-offset-2 transition-colors duration-[var(--dur-ui)]
                     hover:text-[var(--ink)]"
        >
          Download a backup
        </a>
      </Shell>

      {/* Fixed to the viewport edges, so neither one can shift the column
          above by a pixel however it is opened (DECISIONS.md 17). Both may
          be open at once; neither remembers that it was. */}
      {railed ? (
        <>
          <Rail
            side="left"
            label="Settings"
            open={settingsOpen}
            onToggle={() => setSettingsOpen((open) => !open)}
          >
            {settingsPanel("bare")}
          </Rail>

          <Rail
            side="right"
            label="Classes"
            open={classesOpen}
            onToggle={() => setClassesOpen((open) => !open)}
          >
            {classManager("bare")}
          </Rail>
        </>
      ) : null}
    </>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-5 py-10 sm:py-14">
      {children}
    </main>
  );
}
