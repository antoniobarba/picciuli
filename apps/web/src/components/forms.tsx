import { useId, useState, type FormEvent, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import { ApiError } from '../api/client';
import { InputError } from '../lib/money';
import { Modal } from './Modal';

/** The message to show for an error raised while saving. */
export function errorMessage(error: unknown): string {
  if (error instanceof InputError || error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

export interface FieldProps {
  label: string;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
  className?: string;
}

export function Field({ label, hint, children, className }: FieldProps) {
  const id = useId();
  return (
    <div className={`field${className ? ` ${className}` : ''}`}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value'> & {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
};

export function TextField({ label, value, onChange, hint, className, ...rest }: InputProps) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => <input id={id} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" {...rest} />}
    </Field>
  );
}

/** Amounts can be negative, and phone number pads have no minus key, so this keeps the full keyboard. */
export function AmountField(props: InputProps) {
  return <TextField placeholder="0.00" className="amount-field" {...props} />;
}

export interface Option<T extends string | number> {
  value: T;
  label: string;
  disabled?: boolean;
}

type SelectProps<T extends string | number> = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'> & {
  label: string;
  value: T | null;
  options: readonly Option<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  hint?: ReactNode;
};

export function SelectField<T extends string | number>({
  label,
  value,
  options,
  onChange,
  placeholder,
  hint,
  className,
  ...rest
}: SelectProps<T>) {
  const numeric = typeof (options[0]?.value ?? value) === 'number';
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => (
        <select
          id={id}
          value={value === null ? '' : String(value)}
          onChange={(e) => onChange((numeric ? Number(e.target.value) : e.target.value) as T)}
          {...rest}
        >
          {value === null || placeholder ? (
            <option value="" disabled>
              {placeholder ?? 'Choose…'}
            </option>
          ) : null}
          {options.map((option) => (
            <option key={String(option.value)} value={String(option.value)} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export interface FormDialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Validate and save; throw `InputError` or `ApiError` to keep the form open. */
  onSubmit: () => Promise<unknown> | unknown;
  saveLabel?: string;
  /** Label of the save button while `onSubmit` runs. */
  busyLabel?: string;
  help?: ReactNode;
  wide?: boolean;
  danger?: boolean;
  /** Extra buttons on the left of the footer, e.g. Delete. */
  secondary?: ReactNode;
  children: ReactNode;
}

/** A form in a dialog: shows errors and stays open until saving succeeds. */
export function FormDialog({
  open,
  onClose,
  title,
  onSubmit,
  saveLabel = 'Save',
  busyLabel = 'Saving…',
  help,
  wide,
  danger,
  secondary,
  children,
}: FormDialogProps) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
      onClose();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={title} wide={wide}>
      <form
        className="form"
        onSubmit={submit}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
            event.preventDefault();
            void submit();
          }
        }}
        noValidate
      >
        <div className="form-body">
          {children}
          {help ? <div className="form-help">{help}</div> : null}
        </div>
        {error ? (
          <div className="form-error" role="alert">
            {error}
          </div>
        ) : null}
        <div className="form-actions">
          {secondary ? <div className="form-actions-secondary">{secondary}</div> : null}
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={`button ${danger ? 'danger' : 'primary'}`} disabled={busy}>
            {busy ? busyLabel : saveLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}
