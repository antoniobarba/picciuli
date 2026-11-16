import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { useAccounts } from '../api/queries';
import type { Schedule, Transaction } from '../api/types';
import { todayDay, type Day } from '../lib/dates';
import { AccountForm } from '../forms/AccountForm';
import { DebtOccurrenceForm } from '../forms/DebtForms';
import { TradeForm, tradeOf } from '../forms/InvestmentForms';
import { ScheduleForm } from '../forms/ScheduleForm';
import { TransactionForm } from '../forms/TransactionForm';

export interface Editors {
  newTransaction: (options?: { day?: Day; accountId?: number | null }) => void;
  editTransaction: (transaction: Transaction) => void;
  /** A new recurring transaction, empty or repeating `from`. */
  newSchedule: (options?: { day?: Day; from?: Transaction }) => void;
  editSchedule: (schedule: Schedule) => void;
  /** Record (possibly changed) or skip the next occurrence of a schedule. */
  confirmOccurrence: (schedule: Schedule, date?: Day) => void;
}

const EditorsContext = createContext<Editors | null>(null);

export function useEditors(): Editors {
  const context = useContext(EditorsContext);
  if (!context) throw new Error('useEditors outside EditorsProvider');
  return context;
}

type EditorState =
  | { kind: 'transaction'; key: number; day: Day; accountId: number | null; transaction: Transaction | null }
  | { kind: 'schedule'; key: number; day: Day; schedule: Schedule | null; from: Transaction | null }
  | { kind: 'occurrence'; key: number; schedule: Schedule; date: Day };

/** Owns the transaction and schedule dialogs, so any screen (or the command palette) can open them. */
export function EditorsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<EditorState | null>(null);
  const counter = useRef(0);
  const nextKey = () => {
    counter.current += 1;
    return counter.current;
  };

  const newTransaction = useCallback<Editors['newTransaction']>(({ day, accountId = null } = {}) => {
    setState({ kind: 'transaction', key: nextKey(), day: day ?? todayDay(), accountId, transaction: null });
  }, []);

  const editTransaction = useCallback((transaction: Transaction) => {
    setState({ kind: 'transaction', key: nextKey(), day: transaction.date, accountId: null, transaction });
  }, []);

  const newSchedule = useCallback<Editors['newSchedule']>(({ day, from } = {}) => {
    setState({ kind: 'schedule', key: nextKey(), day: day ?? todayDay(), schedule: null, from: from ?? null });
  }, []);

  const editSchedule = useCallback((schedule: Schedule) => {
    setState({ kind: 'schedule', key: nextKey(), day: todayDay(), schedule, from: null });
  }, []);

  const confirmOccurrence = useCallback((schedule: Schedule, date?: Day) => {
    const day = date ?? schedule.next_date;
    if (day) setState({ kind: 'occurrence', key: nextKey(), schedule, date: day });
  }, []);

  const value = useMemo(
    () => ({ newTransaction, editTransaction, newSchedule, editSchedule, confirmOccurrence }),
    [newTransaction, editTransaction, newSchedule, editSchedule, confirmOccurrence],
  );

  return (
    <EditorsContext.Provider value={value}>
      {children}
      {state ? (
        <Editor key={state.key} state={state} onClose={() => setState(null)} onMakeRecurring={(from) => newSchedule({ from })} />
      ) : null}
    </EditorsContext.Provider>
  );
}

/** Buys and sells open in the trade form, any other transaction in the transaction form. */
function Editor({
  state,
  onClose,
  onMakeRecurring,
}: {
  state: EditorState;
  onClose: () => void;
  onMakeRecurring: (transaction: Transaction) => void;
}) {
  const transaction = state.kind === 'transaction' ? state.transaction : null;
  const trade = useMemo(() => (transaction ? tradeOf(transaction) : null), [transaction]);
  const accounts = useAccounts(true).data;
  if (state.kind === 'schedule') {
    const debt = state.schedule?.debt;
    if (debt && debt.kind !== 'loan_payment') {
      // Card interest and minimum payments follow the terms of the card.
      const card = accounts?.find((account) => account.id === debt.account_id);
      return card ? <AccountForm account={card} onClose={onClose} /> : null;
    }
    return <ScheduleForm onClose={onClose} schedule={state.schedule} from={state.from} day={state.day} />;
  }
  if (state.kind === 'occurrence') {
    if (state.schedule.debt) {
      return <DebtOccurrenceForm schedule={state.schedule} date={state.date} onClose={onClose} />;
    }
    return (
      <TransactionForm
        open
        onClose={onClose}
        day={state.date}
        occurrence={{ schedule: state.schedule, date: state.date }}
      />
    );
  }
  if (transaction && trade) {
    return <TradeForm selling={trade.selling} editing={{ transaction, trade }} onClose={onClose} />;
  }
  return (
    <TransactionForm
      open
      onClose={onClose}
      day={state.day}
      accountId={state.accountId}
      transaction={transaction}
      onMakeRecurring={onMakeRecurring}
    />
  );
}
