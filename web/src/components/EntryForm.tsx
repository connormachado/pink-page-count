import { useState } from "react";
import { ApiError, ServerUnreachable, api } from "../api";
import { defaultClassId } from "../classes";
import { parsePage, previewLine } from "../pages";
import type { Class, Entry } from "../types";
import { ClassPicker } from "./ClassPicker";
import { Field, buttonClasses, inputClasses } from "./Field";

type Props = {
  /** Refetch stats and entries. The form never touches a displayed total itself. */
  onSaved: () => Promise<void>;
  onUnreachable: () => void;
  classes: Class[];
  /** Newest first, straight from the server. Only used to pick the default
   * class -- no total is ever derived from it (DECISIONS.md 7.1). */
  entries: Entry[];
};

type Errors = { start?: string; end?: string; form?: string };

/** Attach a server message to the input it is about (DECISIONS.md 4.2 messages
 * name the field). Anything we can't place goes above the button. */
export function placeMessage(message: string): keyof Errors {
  if (message.includes("page_end")) return "end";
  if (message.includes("page_start")) return "start";
  return "form";
}

export function EntryForm({ onSaved, onUnreachable, classes, entries }: Props) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [saving, setSaving] = useState(false);

  /** undefined means "she hasn't touched the picker", so the default below stays
   * live as entries arrive. A background refresh can therefore never clobber a
   * choice she made, and after a save this resets so the next default is derived
   * from fresh server data. */
  const [chosenClass, setChosenClass] = useState<string | null | undefined>(undefined);
  const selectedClass = chosenClass === undefined
    ? defaultClassId(entries, classes)
    : chosenClass;

  const preview = previewLine(start, end);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const pageStart = parsePage(start);
    const pageEnd = parsePage(end);

    // Only the things we cannot ask the server about -- an empty box is not a
    // request. Everything else is the server's call.
    const local: Errors = {};
    if (pageStart === null) local.start = "Add the page you started on.";
    if (pageEnd === null) local.end = "Add the page you stopped on.";
    if (local.start || local.end) {
      setErrors(local);
      return;
    }

    setSaving(true);
    setErrors({});
    try {
      await api.create({
        page_start: pageStart as number,
        page_end: pageEnd as number,
        note: note.trim() === "" ? null : note.trim(),
        // Optional, and never checked above: nothing about the class can stop
        // a save (DECISIONS.md 12.4).
        class_id: selectedClass,
      });
      setStart("");
      setEnd("");
      setNote("");
      setChosenClass(undefined);
      await onSaved();
    } catch (error) {
      if (error instanceof ServerUnreachable) onUnreachable();
      else if (error instanceof ApiError) setErrors({ [placeMessage(error.message)]: error.message });
      else throw error;
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="rounded-2xl border border-[var(--pink-edge)] bg-[var(--pink-surface)] p-5"
    >
      <div className="flex flex-wrap items-start gap-3">
        <Field id="page-start" label="Start page" error={errors.start} className="w-28">
          <input
            id="page-start"
            name="page_start"
            inputMode="numeric"
            autoComplete="off"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-describedby={errors.start ? "page-start-error" : undefined}
            className={inputClasses}
          />
        </Field>

        <Field id="page-end" label="End page" error={errors.end} className="w-28">
          <input
            id="page-end"
            name="page_end"
            inputMode="numeric"
            autoComplete="off"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-describedby={errors.end ? "page-end-error" : undefined}
            className={inputClasses}
          />
        </Field>

        <Field id="note" label="Note (optional)" className="min-w-40 flex-1">
          <input
            id="note"
            name="note"
            autoComplete="off"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className={inputClasses}
          />
        </Field>

        <div className="pt-6">
          <button type="submit" disabled={saving} className={buttonClasses}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {classes.length > 0 ? (
        <div className="mt-3">
          <ClassPicker
            classes={classes}
            value={selectedClass}
            onChange={setChosenClass}
            idPrefix="new-entry"
          />
        </div>
      ) : null}

      {/* A preview of an unsaved input: end - start + 1, display only, never
          sent. Every saved number on this page comes from the server. */}
      <p className="mt-3 h-5 text-sm text-[var(--rose-muted)]" aria-live="polite">
        {preview}
      </p>

      {errors.form ? (
        <p role="status" className="mt-1 text-sm text-[var(--rose-muted)]">
          {errors.form}
        </p>
      ) : null}
    </form>
  );
}
