/** Tabs (switch between views of a page) and SegmentedControl (pick one option, e.g. group by). */
import { type KeyboardEvent, type ReactNode, useRef } from "react";

import { cn } from "../../lib/cn.ts";

export interface ChoiceOption<V extends string> {
  value: V;
  label: ReactNode;
  testId?: string;
}

interface ChoiceProps<V extends string> {
  label: string;
  options: ChoiceOption<V>[];
  value: V;
  onChange: (value: V) => void;
}

/** Buttons in one frame; the chosen one is filled. Pressed state for screen readers. */
export function SegmentedControl<V extends string>({ label, options, value, onChange }: ChoiceProps<V>) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap rounded-control border border-line-strong bg-surface p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          data-testid={option.testId}
          onClick={() => onChange(option.value)}
          className={cn(
            "min-h-10 rounded-[0.375rem] px-3 text-body font-semibold",
            option.value === value ? "bg-accent text-on-accent" : "text-ink hover:bg-surface-muted",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Tabs with arrow-key navigation (WAI-ARIA tabs pattern). */
export function Tabs<V extends string>({ label, options, value, onChange }: ChoiceProps<V>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(event: KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = (index + step + options.length) % options.length;
    refs.current[next]?.focus();
    const option = options[next];
    if (option) onChange(option.value);
  }
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-line">
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            data-testid={option.testId}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKey(event, index)}
            className={cn(
              "-mb-px min-h-11 border-b-2 px-4 text-body font-semibold",
              selected ? "border-accent text-accent" : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
