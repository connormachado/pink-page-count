import { useId, type ReactNode } from "react";

type Props = {
  /** Which viewport edge this rail is pinned to. */
  side: "left" | "right";
  /** The rail's only text, and the same word the collapsed panel already
   * carried as its <summary>. Nothing new is written on screen here (§8). */
  label: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
};

/** One collapsible edge rail (DECISIONS.md 17). There is one of these at each
 * edge at every width; nothing about it is conditional on a breakpoint.
 *
 * The rail is `position: fixed`, which is the whole reason the center column
 * cannot move: a fixed element is out of flow, so opening a rail changes no
 * other element's width or offset, and an open panel overlays the column
 * rather than displacing it. The guarantee is structural, not a set of widths
 * that happen to add up.
 *
 * One button, not two. The vertical tab stays put at the viewport edge in
 * both states and the panel grows inward beside it, so a keyboard user who
 * opens a rail still has focus on the same control that closes it.
 *
 * Open/closed is UI state, held by App and nowhere else. It is never written
 * to settings.json -- it is where she is looking right now, not something
 * about her app that should survive a reload (DECISIONS.md 17). */
export function Rail({ side, label, open, onToggle, children }: Props) {
  const panelId = useId();

  // Points at where the panel goes: inward when it is closed, back toward the
  // edge when it is open. Decoration, aria-hidden, and not a word.
  const inward = side === "left" ? "›" : "‹";
  const outward = side === "left" ? "‹" : "›";

  return (
    <aside className={`rail rail-${side}`} data-open={open} aria-label={label}>
      <button
        type="button"
        className="rail-tab"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={onToggle}
      >
        <span className="rail-tab-label">{label}</span>
        <span className="rail-tab-mark" aria-hidden="true">
          {open ? outward : inward}
        </span>
      </button>

      <div id={panelId} className="rail-panel">
        {children}
      </div>
    </aside>
  );
}
