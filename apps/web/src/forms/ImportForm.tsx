import { useState } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation } from '../api/queries';
import type { ImportResult } from '../api/types';
import { useNotify } from '../components/feedback';
import { FormDialog } from '../components/forms';

export type ImportMode = 'merge' | 'replace';

const MODES: Record<ImportMode, { label: string; help: string }> = {
  merge: {
    label: 'Merge with my data',
    help:
      'Adds what is in the file to your data. Accounts, categories, securities and periods with the same name are ' +
      'reused and transactions you already have are skipped, so importing the same file twice adds nothing. Your ' +
      'settings are kept: the file must use the same currency.',
  },
  replace: {
    label: 'Replace my data',
    help:
      'Deletes all your accounts, transactions, budgets and prices, then loads the file, settings included. ' +
      'Export a copy first if unsure.',
  },
};

const COUNTS: readonly (readonly [Exclude<keyof ImportResult, 'replaced' | 'duplicates'>, string, string])[] = [
  ['transactions', 'transaction', 'transactions'],
  ['accounts', 'account', 'accounts'],
  ['categories', 'category', 'categories'],
  ['periods', 'period', 'periods'],
  ['budgets', 'budget', 'budgets'],
  ['securities', 'security', 'securities'],
  ['prices', 'price', 'prices'],
  ['exchange_rates', 'exchange rate', 'exchange rates'],
];

/** A one-line description of what an import added. */
export function describeImport(result: ImportResult): string {
  const parts = COUNTS.filter(([key]) => result[key] > 0).map(
    ([key, one, many]) => `${result[key]} ${result[key] === 1 ? one : many}`,
  );
  const added = parts.length ? `Added ${parts.join(', ')}.` : 'Nothing new to add.';
  if (!result.duplicates) return added;
  const skipped = result.duplicates === 1 ? 'transaction was' : 'transactions were';
  return `${added} ${result.duplicates} ${skipped} already there.`;
}

function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface ImportFormProps {
  /** The chosen database file; the dialog is open while it is set. */
  file: File | null;
  onClose: () => void;
}

/** Load a Picciuli database file (e.g. a previous export), merging or replacing. */
export function ImportForm({ file, onClose }: ImportFormProps) {
  const notify = useNotify();
  const [mode, setMode] = useState<ImportMode>('merge');

  const upload = useApiMutation((api, variables: { file: File; mode: ImportMode }) =>
    unwrap(
      api.POST('/api/v1/me/import', {
        params: { query: { mode: variables.mode } },
        // The body is the raw file, not JSON.
        body: variables.file as unknown as string,
        bodySerializer: (body) => body,
        headers: { 'Content-Type': 'application/vnd.sqlite3' },
      }),
    ),
  );

  const submit = async () => {
    if (!file) return;
    const result = await upload.mutateAsync({ file, mode });
    notify(describeImport(result), {
      title: result.replaced ? 'Data replaced' : 'Data merged',
      kind: 'success',
    });
  };

  return (
    <FormDialog
      open={file !== null}
      onClose={onClose}
      title="Import data"
      onSubmit={submit}
      saveLabel={mode === 'replace' ? 'Replace everything' : 'Merge'}
      busyLabel="Importing…"
      danger={mode === 'replace'}
      help={MODES[mode].help}
    >
      {file ? (
        <p className="import-file">
          <span className="mono">{file.name}</span> <span className="muted small">· {fileSize(file.size)}</span>
        </p>
      ) : null}
      <div className="segmented" role="tablist" aria-label="Import mode">
        {(Object.keys(MODES) as ImportMode[]).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            className={mode === value ? 'active' : ''}
            onClick={() => setMode(value)}
            data-autofocus={value === 'merge' ? true : undefined}
          >
            {MODES[value].label}
          </button>
        ))}
      </div>
    </FormDialog>
  );
}
