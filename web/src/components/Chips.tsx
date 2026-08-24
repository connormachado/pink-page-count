import { CHIPS, type StatKey } from "../stat";

type Props = {
  selected: StatKey;
  onSelect: (key: StatKey) => void;
};

/** Three buttons that change which number is displayed. They fetch nothing --
 * all three values are already in the /api/stats payload we hold. */
export function Chips({ selected, onSelect }: Props) {
  return (
    <div className="flex justify-center gap-2" role="group" aria-label="Which number to show">
      {CHIPS.map((chip) => {
        const isSelected = chip.key === selected;
        return (
          <button
            key={chip.key}
            type="button"
            aria-pressed={isSelected}
            onClick={() => onSelect(chip.key)}
            className={[
              "rounded-full px-4 py-1.5 text-sm border transition-colors",
              "duration-[var(--dur-ui)] cursor-pointer",
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
  );
}
