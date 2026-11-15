import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Transaction } from '../api/types';
import { todayDay, type Day } from '../lib/dates';
import { TransactionForm } from '../forms/TransactionForm';

export interface Editors {
  newTransaction: (options?: { day?: Day; accountId?: number | null }) => void;
  editTransaction: (transaction: Transaction) => void;
}

const EditorsContext = createContext<Editors | null>(null);

export function useEditors(): Editors {
  const context = useContext(EditorsContext);
  if (!context) throw new Error('useEditors outside EditorsProvider');
  return context;
}

interface TransactionEditorState {
  key: number;
  day: Day;
  accountId: number | null;
  transaction: Transaction | null;
}

/** Owns the transaction dialog, so any screen (or the command palette) can open it. */
export function EditorsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<TransactionEditorState | null>(null);
  const counter = useRef(0);

  const newTransaction = useCallback<Editors['newTransaction']>(({ day, accountId = null } = {}) => {
    counter.current += 1;
    setState({ key: counter.current, day: day ?? todayDay(), accountId, transaction: null });
  }, []);

  const editTransaction = useCallback((transaction: Transaction) => {
    counter.current += 1;
    setState({ key: counter.current, day: transaction.date, accountId: null, transaction });
  }, []);

  const value = useMemo(() => ({ newTransaction, editTransaction }), [newTransaction, editTransaction]);

  return (
    <EditorsContext.Provider value={value}>
      {children}
      {state ? (
        <TransactionForm
          key={state.key}
          open
          onClose={() => setState(null)}
          day={state.day}
          accountId={state.accountId}
          transaction={state.transaction}
        />
      ) : null}
    </EditorsContext.Provider>
  );
}
