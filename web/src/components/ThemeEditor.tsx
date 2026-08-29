import { useEffect, useRef, useState } from "react";
import { ApiError, ServerUnreachable, api } from "../api";
import { contrastRatio, MIN_BODY_CONTRAST, MIN_LARGE_CONTRAST } from "../contrast";
import {
  PRESETS,
  SEMANTIC_TOKENS,
  TOKEN_LABELS,
  type CustomTheme,
  type SemanticToken,
} from "../theme";
import type { Settings } from "../types";

type Props = {
  settings: Settings;
  /** The live-computed value of every semantic token, read once by App right
   * after it applies the theme -- never read here, so there is no race
   * against App's own theme-application effect (DECISIONS.md 13). Null for
   * the brief tick before the first resolution completes. */
  resolvedTheme: Record<SemanticToken, string> | null;
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
};

const CONTRAST_PAIRS: ReadonlyArray<{
  a: SemanticToken;
  b: SemanticToken;
  min: number;
  label: string;
}> = [
  {
    a: "--ink",
    b: "--pink-surface",
    min: MIN_BODY_CONTRAST,
    label: "Main text on the card surface",
  },
  {
    a: "--rose-muted",
    b: "--pink-surface",
    min: MIN_BODY_CONTRAST,
    label: "Secondary text on the card surface",
  },
  {
    a: "--rose-muted",
    b: "--pink-wash",
    min: MIN_BODY_CONTRAST,
    label: "Secondary text on the page background",
  },
  {
    a: "--pink-hot",
    b: "--pink-wash",
    min: MIN_LARGE_CONTRAST,
    label: "The primary number on the page background",
  },
];

/** Preset picker, per-token color inputs with live preview, inline contrast
 * warnings, and the always-reachable reset-to-preset escape hatch.
 * DECISIONS.md 13. */
export function ThemeEditor({ settings, resolvedTheme, onChanged, onUnreachable }: Props) {
  const [draft, setDraft] = useState(resolvedTheme);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Re-sync whenever App recomputes the resolved theme -- a preset switch, a
  // reset, or any settings change made elsewhere.
  useEffect(() => {
    setDraft(resolvedTheme);
  }, [resolvedTheme]);

  function handleFailure(caught: unknown) {
    if (caught instanceof ServerUnreachable) onUnreachable();
    else if (caught instanceof ApiError) setError(caught.message);
    else throw caught;
  }

  async function selectPreset(id: string) {
    setBusy(true);
    setError(null);
    try {
      // Switching preset clears any customization -- overrides tuned for one
      // palette can clash against another's.
      await api.updateSettings({ theme: id, custom_theme: null });
      await onChanged();
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  function previewToken(token: SemanticToken, value: string) {
    document.documentElement.style.setProperty(token, value);
    setDraft((prev) => ({ ...(prev ?? ({} as Record<SemanticToken, string>)), [token]: value }));
  }

  async function commitToken(token: SemanticToken, value: string) {
    const merged: CustomTheme = { ...(settings.custom_theme ?? {}), [token]: value };
    setBusy(true);
    setError(null);
    try {
      await api.updateSettings({ theme: "custom", custom_theme: merged });
      await onChanged();
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  async function resetToPreset() {
    setBusy(true);
    setError(null);
    try {
      await api.updateSettings({ custom_theme: null });
      await onChanged();
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  const warnings = draft
    ? CONTRAST_PAIRS.filter((pair) => contrastRatio(draft[pair.a], draft[pair.b]) < pair.min)
    : [];

  return (
    <div className="flex flex-col gap-4">
      <fieldset>
        <legend className="mb-1 block text-sm text-[var(--rose-muted)]">Theme</legend>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              disabled={busy}
              onClick={() => void selectPreset(preset.id)}
              aria-pressed={settings.theme === preset.id}
              className={[
                "rounded-full px-4 py-1.5 text-sm border transition-colors",
                "duration-[var(--dur-ui)] cursor-pointer disabled:cursor-default",
                settings.theme === preset.id
                  ? "bg-[var(--pink-edge)] border-[var(--pink-edge)] text-[var(--ink)]"
                  : "bg-transparent border-[var(--pink-edge)] text-[var(--rose-muted)] hover:bg-[var(--pink-surface)]",
              ].join(" ")}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </fieldset>

      {/* The escape hatch. Styled with the fixed --chrome-safe-* tokens, not
          the semantic ones -- it must stay legible even when a custom theme
          has made everything else hard to read (DECISIONS.md 13). Always
          rendered, never gated on the contrast check below. */}
      <button
        type="button"
        onClick={() => void resetToPreset()}
        disabled={busy}
        className="self-start rounded-full border border-[var(--chrome-safe-border)]
                   bg-[var(--chrome-safe-bg)] px-4 py-2 text-sm text-[var(--chrome-safe-text)]
                   cursor-pointer transition-colors duration-[var(--dur-ui)]
                   disabled:opacity-60 disabled:cursor-default"
      >
        Reset to preset
      </button>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 block text-sm text-[var(--rose-muted)]">Custom colors</legend>
        {SEMANTIC_TOKENS.map((token) => (
          <ColorField
            key={token}
            token={token}
            value={draft?.[token] || "#000000"}
            onPreview={(value) => previewToken(token, value)}
            onCommit={(value) => void commitToken(token, value)}
          />
        ))}
      </fieldset>

      {warnings.length > 0 ? (
        <div role="status" className="flex flex-col gap-1 text-sm text-[var(--rose-muted)]">
          {warnings.map((pair) => (
            <p key={pair.label}>{pair.label} is hard to read at this contrast.</p>
          ))}
        </div>
      ) : null}

      {error ? (
        <p role="status" className="text-sm text-[var(--rose-muted)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** One color input. React remaps its `onChange` prop to listen for the
 * native "input" event on text-like inputs (which "color" counts as), so it
 * cannot tell drag-in-progress apart from commit -- exactly what this field
 * needs to distinguish. The commit handler is attached as a genuine native
 * "change" listener via a ref instead, which fires once, when the picker
 * closes. */
function ColorField({
  token,
  value,
  onPreview,
  onCommit,
}: {
  token: SemanticToken;
  value: string;
  onPreview: (value: string) => void;
  onCommit: (value: string) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const input = ref.current;
    if (!input) return;
    const handleChange = (event: Event) => {
      onCommit((event.target as HTMLInputElement).value);
    };
    input.addEventListener("change", handleChange);
    return () => input.removeEventListener("change", handleChange);
  }, [onCommit]);

  return (
    <div className="flex items-center gap-3">
      <label htmlFor={`theme-token-${token}`} className="w-40 shrink-0 text-sm text-[var(--ink)]">
        {TOKEN_LABELS[token]}
      </label>
      <input
        ref={ref}
        id={`theme-token-${token}`}
        type="color"
        value={value}
        onInput={(event) => onPreview(event.currentTarget.value)}
        // React remaps onChange to the native "input" event for a color
        // input (see the comment above) -- this is functionally the same
        // preview call as onInput, kept only to satisfy React's controlled-
        // input requirement that a value prop have an onChange handler.
        onChange={(event) => onPreview(event.currentTarget.value)}
        className="h-8 w-14 cursor-pointer rounded border border-[var(--pink-edge)] bg-transparent"
      />
    </div>
  );
}
