import { pickableClasses } from "../classes";
import type { Class } from "../types";
import { ClassDot } from "./ClassDot";

type Props = {
  classes: Class[];
  /** The selected class id, or null for "no class". */
  value: string | null;
  onChange: (id: string | null) => void;
  /** Unique per form, so two pickers on one page get separate radio groups. */
  idPrefix: string;
};

const pillClasses = [
  "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1",
  "text-sm border-[var(--pink-edge)] bg-transparent text-[var(--rose-muted)]",
  "transition-colors duration-[var(--dur-ui)] hover:bg-[var(--pink-wash)]",
  "peer-checked:bg-[var(--pink-edge)] peer-checked:text-[var(--ink)]",
  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2",
  "peer-focus-visible:outline-[var(--rose-muted)]",
].join(" ");

/** The optional class picker. Inline, one tap, never required.
 *
 * Real radio inputs rather than buttons, so arrow-key navigation and the
 * "one of these" relationship come from the platform. Nothing here can block a
 * save: the form does not read this value for validation, and "No class" is
 * always the first option (DECISIONS.md 12.4). */
export function ClassPicker({ classes, value, onChange, idPrefix }: Props) {
  const options = pickableClasses(classes, value);
  if (options.length === 0) return null;

  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 block text-sm text-[var(--rose-muted)]">
        Class <span className="opacity-80">(optional)</span>
      </legend>
      <div className="flex flex-wrap gap-2">
        {[null, ...options.map((item) => item.id)].map((id) => {
          const subject = id === null ? undefined : options.find((c) => c.id === id);
          const optionId = `${idPrefix}-class-${id ?? "none"}`;
          return (
            <span key={id ?? "none"}>
              <input
                type="radio"
                id={optionId}
                name={`${idPrefix}-class`}
                className="peer sr-only"
                checked={value === id}
                onChange={() => onChange(id)}
              />
              <label htmlFor={optionId} className={pillClasses}>
                <ClassDot subject={subject} />
                {subject ? subject.title : "No class"}
                {subject?.archived ? (
                  <span className="opacity-70">(archived)</span>
                ) : null}
              </label>
            </span>
          );
        })}
      </div>
    </fieldset>
  );
}
