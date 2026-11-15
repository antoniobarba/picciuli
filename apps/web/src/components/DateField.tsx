import { useRef, type ReactNode } from 'react';
import { shortDate, weekday, WEEKDAY_SHORT, type Day } from '../lib/dates';
import { parseDate } from '../lib/forms';
import { Field } from './forms';

export interface DateFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  today: Day;
  placeholder?: string;
  hint?: ReactNode;
  autoFocus?: boolean;
}

/**
 * A typed date (`2025-02-03`, `3/2`, `today`, `+7`…) with the native date
 * picker one tap away, which is what phones are good at.
 */
export function DateField({ label, value, onChange, today, placeholder, hint, autoFocus }: DateFieldProps) {
  const picker = useRef<HTMLInputElement>(null);
  let resolved: Day | null = null;
  let invalid = false;
  if (value.trim()) {
    try {
      resolved = parseDate(value, today);
    } catch {
      invalid = true;
    }
  }
  const preview =
    resolved && resolved !== value.trim()
      ? `${WEEKDAY_SHORT[weekday(resolved)]} ${shortDate(resolved)}`
      : resolved
        ? WEEKDAY_SHORT[weekday(resolved)]
        : null;

  const openPicker = () => {
    const input = picker.current;
    if (!input) return;
    try {
      input.showPicker();
    } catch {
      input.click();
    }
  };

  return (
    <Field
      label={label}
      hint={
        invalid ? (
          <span className="negative">Not a date yet: try 2025-02-03, 3/2, today or +7</span>
        ) : (
          (hint ?? preview)
        )
      }
    >
      {(id) => (
        <div className="date-input">
          <input
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            autoFocus={autoFocus}
            aria-invalid={invalid || undefined}
          />
          <button type="button" className="icon-button" onClick={openPicker} aria-label="Pick a date" tabIndex={-1}>
            <CalendarIcon />
          </button>
          <input
            ref={picker}
            type="date"
            className="date-picker"
            tabIndex={-1}
            aria-hidden="true"
            value={resolved ?? ''}
            onChange={(e) => e.target.value && onChange(e.target.value)}
          />
        </div>
      )}
    </Field>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        d="M5 6h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zM4 10h16M8 3v4M16 3v4"
      />
    </svg>
  );
}
