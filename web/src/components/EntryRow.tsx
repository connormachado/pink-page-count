import { useState } from "react";
import { ApiError, ServerUnreachable, api } from "../api";
import { findClass } from "../classes";
import { formatReadAt, moveToDate, toDateInput } from "../dates";
import { parsePage, plural, previewLine } from "../pages";
import type { Class, Entry, EntryPatch } from "../types";
import { ClassDot } from "./ClassDot";
import { ClassPicker } from "./ClassPicker";
import { placeMessage } from "./EntryForm";
import { Field, buttonClasses, inputClasses, quietButtonClasses } from "./Field";

type Props = {
  entry: Entry;
  classes: Class[];
  onChanged: () => Promise<void>;
  onUnreachable: () => void;
};

type Mode = "view" | "edit" | "confirm-delete";
type Errors = { start?: string; end?: string; form?: string };

const rowClasses =
  "rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] p-4";

export function EntryRow({ entry, classes, onChanged, onUnreachable }: Props) {
  const [mode, setMode] = useState<Mode>("view");
  const [start, setStart] = useState(String(entry.page_start));
  const [end, setEnd] = useState(String(entry.page_end));
  const [note, setNote] = useState(entry.note ?? "");
  const [readDate, setReadDate] = useState(toDateInput(entry.read_at));
  const [classId, setClassId] = useState<string | null>(entry.class_id);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  /** undefined when the id names a class that no longer exists. That is not an
   * error -- the row simply shows no class (DECISIONS.md 1.3). */
  const subject = findClass(classes, entry.class_id);

  function startEditing() {
    // Prefill from the entry every time, so an abandoned edit leaves nothing behind.
    setStart(String(entry.page_start));
    setEnd(String(entry.page_end));
    setNote(entry.note ?? "");
    setReadDate(toDateInput(entry.read_at));
    setClassId(entry.class_id);
    setErrors({});
    setMode("edit");
  }

  function handleFailure(error: unknown) {
    if (error instanceof ServerUnreachable) onUnreachable();
    else if (error instanceof ApiError)
      setErrors({ [placeMessage(error.message)]: error.message });
    else throw error;
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    const pageStart = parsePage(start);
    const pageEnd = parsePage(end);

    const local: Errors = {};
    if (pageStart === null) local.start = "Add the page you started on.";
    if (pageEnd === null) local.end = "Add the page you stopped on.";
    if (local.start || local.end) {
      setErrors(local);
      return;
    }

    // Only what actually changed goes on the wire (PATCH, not PUT).
    const changes: EntryPatch = {};
    if (pageStart !== entry.page_start) changes.page_start = pageStart as number;
    if (pageEnd !== entry.page_end) changes.page_end = pageEnd as number;
    const trimmedNote = note.trim() === "" ? null : note.trim();
    if (trimmedNote !== entry.note) changes.note = trimmedNote;
    if (readDate && readDate !== toDateInput(entry.read_at)) {
      changes.read_at = moveToDate(entry.read_at, readDate);
    }
    if (classId !== entry.class_id) changes.class_id = classId;

    if (Object.keys(changes).length === 0) {
      setMode("view");
      return;
    }

    setBusy(true);
    setErrors({});
    try {
      await api.update(entry.id, changes);
      setMode("view");
      await onChanged();
    } catch (error) {
      handleFailure(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await api.remove(entry.id);
      await onChanged();
    } catch (error) {
      setMode("view");
      handleFailure(error);
    } finally {
      setBusy(false);
    }
  }

  if (mode === "edit") {
    const preview = previewLine(start, end);
    return (
      <li className={rowClasses}>
        <form onSubmit={handleSave} noValidate>
          <div className="flex flex-wrap items-start gap-3">
            <Field id={`start-${entry.id}`} label="Start page" error={errors.start} className="w-24">
              <input
                id={`start-${entry.id}`}
                inputMode="numeric"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className={inputClasses}
              />
            </Field>
            <Field id={`end-${entry.id}`} label="End page" error={errors.end} className="w-24">
              <input
                id={`end-${entry.id}`}
                inputMode="numeric"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className={inputClasses}
              />
            </Field>
            <Field id={`date-${entry.id}`} label="Date read" className="w-44">
              <input
                id={`date-${entry.id}`}
                type="date"
                value={readDate}
                onChange={(e) => setReadDate(e.target.value)}
                className={inputClasses}
              />
            </Field>
            <Field id={`note-${entry.id}`} label="Note" className="min-w-40 flex-1">
              <input
                id={`note-${entry.id}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className={inputClasses}
              />
            </Field>
          </div>

          {classes.length > 0 ? (
            <div className="mt-3">
              {/* Passing the entry's own class keeps an archived one visible
                  here, so an edit can never silently strip it (12.4). */}
              <ClassPicker
                classes={classes}
                value={classId}
                onChange={setClassId}
                idPrefix={`entry-${entry.id}`}
              />
            </div>
          ) : null}

          <p className="mt-3 h-5 text-sm text-[var(--rose-muted)]" aria-live="polite">
            {preview}
          </p>

          {errors.form ? (
            <p role="status" className="mb-2 text-sm text-[var(--rose-muted)]">
              {errors.form}
            </p>
          ) : null}

          <div className="mt-2 flex gap-2">
            <button type="submit" disabled={busy} className={buttonClasses}>
              {busy ? "Saving…" : "Save changes"}
            </button>
            <button type="button" onClick={() => setMode("view")} className={quietButtonClasses}>
              Cancel
            </button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className={rowClasses}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-[var(--ink)]">
            Pages {entry.page_start}–{entry.page_end}{" "}
            <span className="text-[var(--rose-muted)]">· {plural(entry.pages, "page")}</span>
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm text-[var(--rose-muted)]">
            {subject ? (
              <>
                {/* The dot is decorative; the name beside it is what carries
                    the meaning, so color is never the only signal. */}
                <ClassDot subject={subject} />
                <span>{subject.title}</span>
                <span aria-hidden="true">·</span>
              </>
            ) : null}
            <span>{formatReadAt(entry.read_at)}</span>
            {entry.note ? <span>· {entry.note}</span> : null}
          </p>
        </div>

        {mode === "confirm-delete" ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--rose-muted)]">Remove this one?</span>
            <button
              type="button"
              disabled={busy}
              onClick={handleDelete}
              className={quietButtonClasses}
            >
              Yes, remove
            </button>
            <button
              type="button"
              onClick={() => setMode("view")}
              className={quietButtonClasses}
            >
              Keep it
            </button>
          </div>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={startEditing}
              aria-label={`Edit pages ${entry.page_start} to ${entry.page_end}`}
              className={quietButtonClasses}
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => setMode("confirm-delete")}
              aria-label={`Delete pages ${entry.page_start} to ${entry.page_end}`}
              className={quietButtonClasses}
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {errors.form ? (
        <p role="status" className="mt-2 text-sm text-[var(--rose-muted)]">
          {errors.form}
        </p>
      ) : null}
    </li>
  );
}
