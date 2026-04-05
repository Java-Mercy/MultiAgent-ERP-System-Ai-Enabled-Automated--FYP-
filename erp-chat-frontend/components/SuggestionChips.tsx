"use client";

const CHIPS = [
  "Show all leads",
  "Show high priority leads",
  "Create a new lead",
  "Draft follow-up email",
  "Generate lead summary",
];

interface SuggestionChipsProps {
  onSelect: (text: string) => void;
  disabled?: boolean;
}

export default function SuggestionChips({ onSelect, disabled }: SuggestionChipsProps) {
  return (
    <div className="flex flex-wrap gap-2 px-4 py-2" style={{ backgroundColor: "#E0E0E0" }}>
      {CHIPS.map((chip) => (
        <button
          key={chip}
          onClick={() => onSelect(chip)}
          disabled={disabled}
          className="chip-btn px-3 py-1.5 rounded-full text-xs font-medium border transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          style={{
            backgroundColor: "#FFFFFF",
            borderColor: "#C49AB8",
            color: "#875A7B",
          }}
        >
          {chip}
        </button>
      ))}
    </div>
  );
}
