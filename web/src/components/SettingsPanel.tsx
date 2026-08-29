import { useState } from "react";
import { ApiError, ServerUnreachable, api } from "../api";
import { CHIP_SETTING_LABELS } from "../stat";
import type { SemanticToken } from "../theme";
import type { ChipSetting, Settings } from "../types";
import { ThemeEditor } from "./ThemeEditor";

type Props = {
  settings: Settings;
  resolvedTheme: Record<SemanticToken, string> | null;
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
};

/** Settings, deliberately out of the way -- the same collapsed <details>
 * pattern as ClassManager, off the save path, closed by default
 * (DECISIONS.md 13, 6). */
export function SettingsPanel({ settings, resolvedTheme, onChanged, onUnreachable }: Props) {
  return (
    <details className="rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] px-5 py-4">
      <summary className="cursor-pointer text-sm text-[var(--rose-muted)]">Settings</summary>

      <div className="mt-4 flex flex-col gap-5">
        <DefaultChipField
          value={settings.default_chip}
          onChanged={onChanged}
          onUnreachable={onUnreachable}
        />
        <ThemeEditor
          settings={settings}
          resolvedTheme={resolvedTheme}
          onChanged={onChanged}
          onUnreachable={onUnreachable}
        />
      </div>
    </details>
  );
}

/** The only control that writes default_chip. Selecting one here changes the
 * setting; it does not move the chip currently on screen -- that only
 * happens on the next load (DECISIONS.md 13). */
function DefaultChipField({
  value,
  onChanged,
  onUnreachable,
}: {
  value: ChipSetting;
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function select(key: ChipSetting) {
    if (key === value) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateSettings({ default_chip: key });
      await onChanged();
    } catch (caught) {
      if (caught instanceof ServerUnreachable) onUnreachable();
      else if (caught instanceof ApiError) setError(caught.message);
      else throw caught;
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset>
      <legend className="mb-1 block text-sm text-[var(--rose-muted)]">Chip shown on load</legend>
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label="Chip shown on load"
      >
        {CHIP_SETTING_LABELS.map((chip) => {
          const isSelected = chip.key === value;
          return (
            <button
              key={chip.key}
              type="button"
              aria-pressed={isSelected}
              disabled={busy}
              onClick={() => void select(chip.key)}
              className={[
                "rounded-full px-4 py-1.5 text-sm border transition-colors",
                "duration-[var(--dur-ui)] cursor-pointer disabled:cursor-default",
                isSelected
                  ? "bg-[var(--pink-edge)] border-[var(--pink-edge)] text-[var(--ink)]"
                  : "bg-transparent border-[var(--pink-edge)] text-[var(--rose-muted)] hover:bg-[var(--pink-surface)]",
              ].join(" ")}
            >
              {chip.label}
            </button>
          );
        })}
      </div>
      {error ? (
        <p role="status" className="mt-1 text-sm text-[var(--rose-muted)]">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
