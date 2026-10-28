import { type ReactNode, useId } from "react";

import { cn } from "../../lib/cn.ts";

/** Classes for inputs and selects: 44 px high, token colours. */
export const controlClass =
  "min-h-11 rounded-control border border-line-strong bg-surface px-3 text-body text-ink placeholder:text-ink-muted";

export interface ControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}

interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  /** Renders the control with the given id and descriptions. */
  children: (props: ControlProps) => ReactNode;
}

/** A labelled control with an optional hint and error, kept outside the label. */
export function Field({ label, hint, error, className, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-small font-semibold text-ink-muted">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && !error && (
        <span id={`${id}-hint`} className="text-small text-ink-muted">
          {hint}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} role="alert" className="text-small font-semibold text-critical">
          {error}
        </span>
      )}
    </div>
  );
}

interface CheckboxFieldProps {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}

/** A checkbox with its label: the whole row (44 px high) is the touch target. */
export function CheckboxField({ label, checked, onChange, disabled, className }: CheckboxFieldProps) {
  return (
    <label
      className={cn(
        "inline-flex min-h-11 cursor-pointer items-center gap-2 text-body text-ink",
        disabled && "cursor-not-allowed opacity-60",
        className,
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-5 w-5 shrink-0 accent-accent"
      />
      {label}
    </label>
  );
}
