import type { ReactNode } from "react";

type Props = {
  id: string;
  label: string;
  error?: string | null;
  children: ReactNode;
  className?: string;
};

/** A labelled control with room for a message underneath it.
 *
 * The message is --rose-muted, never a danger color: DECISIONS.md 8 rules out
 * red and alarm states everywhere, errors included. A wrong number is a typo,
 * not a failing grade.
 */
export function Field({ id, label, error, children, className }: Props) {
  return (
    // A field carrying a message takes the full row so the message has room to
    // be read. The control keeps its own width either way.
    <div className={error ? "w-full" : className}>
      <label htmlFor={id} className="block text-sm text-[var(--rose-muted)] mb-1">
        {label}
      </label>
      <div className={error ? className : "w-full"}>{children}</div>
      {error ? (
        <p id={`${id}-error`} role="status" className="mt-1 text-sm text-[var(--rose-muted)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const inputClasses =
  "w-full rounded-lg border border-[var(--pink-edge)] bg-[var(--pink-surface)] px-3 py-2 " +
  "text-[var(--ink)] transition-colors duration-[var(--dur-ui)] " +
  "placeholder:text-[var(--rose-muted)]";

export const buttonClasses =
  "rounded-full border border-[var(--pink-edge)] bg-[var(--pink-edge)] px-5 py-2 " +
  "text-[var(--ink)] transition-colors duration-[var(--dur-ui)] cursor-pointer " +
  "hover:bg-[var(--pink-surface)] disabled:opacity-60 disabled:cursor-default";

export const quietButtonClasses =
  "rounded-full border border-[var(--pink-edge)] bg-transparent px-3 py-1 text-sm " +
  "text-[var(--rose-muted)] transition-colors duration-[var(--dur-ui)] cursor-pointer " +
  "hover:bg-[var(--pink-surface)]";
