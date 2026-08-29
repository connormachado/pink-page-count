import { useState } from "react";
import { ApiError, ServerUnreachable, api } from "../api";
import { paletteColors, suggestColor } from "../palette";
import type { Class } from "../types";
import { ClassDot } from "./ClassDot";
import { buttonClasses, inputClasses, quietButtonClasses } from "./Field";
import type { PanelChrome } from "./Rail";

type Props = {
  classes: Class[];
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
  /** Who owns the disclosure -- see PanelChrome. The stacked card below the
   * entry log, or bare inside the right rail (DECISIONS.md 17). */
  chrome?: PanelChrome;
};

/** Class management, deliberately out of the way.
 *
 * Closed by default and never on the save path: a collapsed <details> under
 * the entry list on a narrow window, a collapsed rail at the right edge on a
 * wide one. Either way it costs nothing to ignore forever. No router, no
 * second screen (DECISIONS.md 12.4, 17, and section 6 still says no router).
 *
 * Nothing in here displays a count, a total, or a comparison between classes.
 * The API returns none, so there is nothing to render (DECISIONS.md 12.5). */
export function ClassManager({ classes, onChanged, onUnreachable, chrome = "details" }: Props) {
  const live = classes.filter((item) => !item.archived);

  const body = (
    <div className={chrome === "details" ? "mt-4 flex flex-col gap-5" : "flex flex-col gap-5"}>
      <NewClassForm
        live={live}
        onChanged={onChanged}
        onUnreachable={onUnreachable}
      />

      {classes.length === 0 ? (
        <p className="text-sm text-[var(--rose-muted)]">
          No classes yet. They're optional — entries save fine without one.
        </p>
      ) : (
        <ul aria-label="Your classes" className="flex flex-col gap-2">
          {classes.map((subject) => (
            <ClassRow
              key={subject.id}
              subject={subject}
              onChanged={onChanged}
              onUnreachable={onUnreachable}
            />
          ))}
        </ul>
      )}
    </div>
  );

  if (chrome === "bare") return body;

  return (
    <details className="rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] px-5 py-4">
      <summary className="cursor-pointer text-sm text-[var(--rose-muted)]">
        Classes
      </summary>
      {body}
    </details>
  );
}

/** The swatch row. Reads the --class-* tokens by name and renders their
 * resolved values; the values themselves live in tokens.css and nowhere else
 * (DECISIONS.md 12.2). Renders nothing if the stylesheet has not loaded, in
 * which case no color is sent and the server's fallback applies. */
function Swatches({
  value,
  onChange,
  idPrefix,
}: {
  value: string | null;
  onChange: (color: string) => void;
  idPrefix: string;
}) {
  const palette = paletteColors();
  if (palette.length === 0) return null;

  return (
    <fieldset>
      <legend className="mb-1 block text-sm text-[var(--rose-muted)]">Color</legend>
      <div className="flex flex-wrap gap-2">
        {palette.map((color) => {
          const optionId = `${idPrefix}-swatch-${color.replace("#", "")}`;
          return (
            <span key={color}>
              <input
                type="radio"
                id={optionId}
                name={`${idPrefix}-swatch`}
                className="peer sr-only"
                checked={value?.toLowerCase() === color.toLowerCase()}
                onChange={() => onChange(color)}
              />
              <label
                htmlFor={optionId}
                aria-label={`Color ${color}`}
                style={{ backgroundColor: color }}
                className={[
                  "block size-6 cursor-pointer rounded-full border-2 border-transparent",
                  "transition-[border-color] duration-[var(--dur-ui)]",
                  "peer-checked:border-[var(--ink)]",
                  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2",
                  "peer-focus-visible:outline-[var(--rose-muted)]",
                ].join(" ")}
              />
            </span>
          );
        })}
      </div>
    </fieldset>
  );
}

function NewClassForm({
  live,
  onChanged,
  onUnreachable,
}: {
  live: Class[];
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
}) {
  const [title, setTitle] = useState("");
  // undefined means "untouched -- use the suggestion", so the suggestion stays
  // current as classes are added and never clobbers a deliberate choice.
  const [color, setColor] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const suggested = suggestColor(
    live.map((item) => item.color),
    live.length,
  );
  const chosen = color ?? suggested;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (title.trim() === "") {
      setError("Give the class a name.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await api.createClass({
        title: title.trim(),
        // The front end picks the color; the server has no palette (12.2).
        ...(chosen !== null ? { color: chosen } : {}),
      });
      setTitle("");
      setColor(undefined);
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
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-40 flex-1">
          <label
            htmlFor="new-class-title"
            className="mb-1 block text-sm text-[var(--rose-muted)]"
          >
            New class
          </label>
          <input
            id="new-class-title"
            value={title}
            autoComplete="off"
            onChange={(e) => setTitle(e.target.value)}
            className={inputClasses}
          />
        </div>
        <button type="submit" disabled={busy} className={buttonClasses}>
          {busy ? "Adding…" : "Add"}
        </button>
      </div>

      <Swatches value={chosen} onChange={setColor} idPrefix="new-class" />

      {error ? (
        <p role="status" className="text-sm text-[var(--rose-muted)]">
          {error}
        </p>
      ) : null}
    </form>
  );
}

type Mode = "view" | "edit" | "confirm-delete";

function ClassRow({
  subject,
  onChanged,
  onUnreachable,
}: {
  subject: Class;
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
}) {
  const [mode, setMode] = useState<Mode>("view");
  const [title, setTitle] = useState(subject.title);
  const [description, setDescription] = useState(subject.description ?? "");
  const [color, setColor] = useState(subject.color);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function startEditing() {
    setTitle(subject.title);
    setDescription(subject.description ?? "");
    setColor(subject.color);
    setError(null);
    setMode("edit");
  }

  function handleFailure(caught: unknown) {
    if (caught instanceof ServerUnreachable) onUnreachable();
    else if (caught instanceof ApiError) setError(caught.message);
    else throw caught;
  }

  async function send(changes: Parameters<typeof api.updateClass>[1]) {
    setBusy(true);
    setError(null);
    try {
      await api.updateClass(subject.id, changes);
      setMode("view");
      await onChanged();
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    const trimmedDescription = description.trim() === "" ? null : description.trim();
    const changes: Parameters<typeof api.updateClass>[1] = {};
    if (title.trim() !== subject.title) changes.title = title.trim();
    if (trimmedDescription !== subject.description) {
      changes.description = trimmedDescription;
    }
    if (color !== subject.color) changes.color = color;

    if (Object.keys(changes).length === 0) {
      setMode("view");
      return;
    }
    await send(changes);
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await api.removeClass(subject.id);
      await onChanged();
    } catch (caught) {
      setMode("view");
      handleFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  if (mode === "edit") {
    return (
      <li className="rounded-xl border border-[var(--pink-edge)] bg-[var(--pink-wash)] p-3">
        <form onSubmit={handleSave} noValidate className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-3">
            <div className="min-w-40 flex-1">
              <label
                htmlFor={`class-title-${subject.id}`}
                className="mb-1 block text-sm text-[var(--rose-muted)]"
              >
                Name
              </label>
              <input
                id={`class-title-${subject.id}`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={inputClasses}
              />
            </div>
            <div className="min-w-40 flex-1">
              <label
                htmlFor={`class-description-${subject.id}`}
                className="mb-1 block text-sm text-[var(--rose-muted)]"
              >
                Note (optional)
              </label>
              <input
                id={`class-description-${subject.id}`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className={inputClasses}
              />
            </div>
          </div>

          <Swatches
            value={color}
            onChange={setColor}
            idPrefix={`class-${subject.id}`}
          />

          {error ? (
            <p role="status" className="text-sm text-[var(--rose-muted)]">
              {error}
            </p>
          ) : null}

          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={buttonClasses}>
              {busy ? "Saving…" : "Save changes"}
            </button>
            <button
              type="button"
              onClick={() => setMode("view")}
              className={quietButtonClasses}
            >
              Cancel
            </button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className="rounded-xl border border-[var(--pink-edge)] bg-[var(--pink-wash)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2 text-[var(--ink)]">
          <ClassDot subject={subject} />
          <span className="truncate">{subject.title}</span>
          {subject.archived ? (
            <span className="text-sm text-[var(--rose-muted)]">· archived</span>
          ) : null}
        </span>

        {mode === "confirm-delete" ? null : (
          <span className="flex gap-2">
            <button type="button" onClick={startEditing} className={quietButtonClasses}>
              Edit
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void send({ archived: !subject.archived })}
              className={quietButtonClasses}
            >
              {subject.archived ? "Unarchive" : "Archive"}
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setMode("confirm-delete");
              }}
              className={quietButtonClasses}
            >
              Delete
            </button>
          </span>
        )}
      </div>

      {subject.description ? (
        <p className="mt-1 text-sm text-[var(--rose-muted)]">{subject.description}</p>
      ) : null}

      {mode === "confirm-delete" ? (
        <div className="mt-3">
          {/* Said plainly, because a delete button that might eat reading
              history is the one thing in this app worth a second tap
              (DECISIONS.md 12.3). */}
          <p className="text-sm text-[var(--ink)]">
            Delete “{subject.title}”? Everything you logged under it is kept — those
            entries just won't have a class any more.
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={handleDelete}
              className={quietButtonClasses}
            >
              Yes, delete the class
            </button>
            <button
              type="button"
              onClick={() => setMode("view")}
              className={quietButtonClasses}
            >
              Keep it
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p role="status" className="mt-2 text-sm text-[var(--rose-muted)]">
          {error}
        </p>
      ) : null}
    </li>
  );
}
