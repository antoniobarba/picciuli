import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation, useBudgetReport, useCategories, useMoney, usePeriods } from '../api/queries';
import type { BudgetLine, Period } from '../api/types';
import { useConfirm, useNotify } from '../components/feedback';
import { AmountField, errorMessage, FormDialog, SelectField } from '../components/forms';
import { Amount, Empty, Loading, PageHeader, ProgressBar, RowMenu } from '../components/ui';
import { covers } from '../lib/calendar';
import { todayDay } from '../lib/dates';
import { categoryTree, periodRange } from '../lib/format';
import { InputError, requiredId } from '../lib/forms';
import { useHotkeys } from '../lib/useHotkeys';

export function Budgets() {
  const money = useMoney();
  const confirm = useConfirm();
  const notify = useNotify();
  const periods = usePeriods();
  const categories = useCategories();
  const ordered = useMemo(
    () => [...(periods.data ?? [])].sort((a, b) => a.start.localeCompare(b.start) || a.id - b.id),
    [periods.data],
  );
  const today = todayDay();
  const [chosenId, setChosenId] = useState<number | null>(null);
  const current =
    ordered.find((p) => p.id === chosenId) ??
    [...ordered].reverse().find((p) => covers(p, today)) ??
    ordered[ordered.length - 1] ??
    null;
  const report = useBudgetReport(current?.id ?? null);
  const [dialog, setDialog] = useState<{ kind: 'edit'; line: BudgetLine | null } | { kind: 'copy' } | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const lines = report.data?.lines ?? [];
  const selected = lines.find((l) => l.budget.id === selectedId) ?? null;

  const step = (delta: number) => {
    if (!current) return;
    const index = ordered.findIndex((p) => p.id === current.id);
    const next = ordered[index + delta];
    if (next) setChosenId(next.id);
  };

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/budgets/{budget_id}', { params: { path: { budget_id: id } } })),
  );
  const deleteBudget = async (line: BudgetLine) => {
    if (await confirm({ title: `Delete the budget for “${line.category.name}”?` })) {
      try {
        await remove.mutateAsync(line.budget.id);
      } catch (error) {
        notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
      }
    }
  };
  const newBudget = () => {
    if (!current) notify('Create a period first: open Periods, then New.', { kind: 'warning' });
    else if (!categories.data?.length) notify('Create a category first: open Categories, then New.', { kind: 'warning' });
    else setDialog({ kind: 'edit', line: null });
  };
  const copy = () => {
    if (ordered.length < 2) notify('There is no other period to copy from.');
    else setDialog({ kind: 'copy' });
  };

  useHotkeys({
    '[': () => step(-1),
    ']': () => step(1),
    n: newBudget,
    e: () => selected && setDialog({ kind: 'edit', line: selected }),
    d: () => selected && void deleteBudget(selected),
    y: copy,
  });

  return (
    <div className="page">
      <PageHeader title="Budgets">
        <button type="button" className="button" onClick={copy} disabled={!current}>
          Copy from…
        </button>
        <button type="button" className="button primary" onClick={newBudget}>
          + New budget
        </button>
      </PageHeader>
      {periods.isLoading ? (
        <Loading />
      ) : !current ? (
        <Empty>Budgets belong to a period: create one in Periods first.</Empty>
      ) : (
        <>
          <div className="period-picker">
            <button
              type="button"
              className="icon-button"
              onClick={() => step(-1)}
              disabled={ordered[0]?.id === current.id}
              aria-label="Previous period"
            >
              ‹
            </button>
            <select
              aria-label="Period"
              value={current.id}
              onChange={(e) => setChosenId(Number(e.target.value))}
            >
              {ordered.map((p: Period) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({periodRange(p)})
                </option>
              ))}
            </select>
            <button
              type="button"
              className="icon-button"
              onClick={() => step(1)}
              disabled={ordered[ordered.length - 1]?.id === current.id}
              aria-label="Next period"
            >
              ›
            </button>
          </div>
          {lines.length === 0 ? (
            <Empty>No budgets in this period. Add one, or copy them from another period.</Empty>
          ) : (
            <div className="card">
              <table className="table rows-clickable">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Budget</th>
                    <th className="num hide-sm">Actual</th>
                    <th className="num">Remaining</th>
                    <th className="hide-sm">Used</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => {
                    const used = line.budget.amount ? -line.actual / line.budget.amount : line.actual < 0 ? 1 : 0;
                    return (
                      <tr
                        key={line.budget.id}
                        tabIndex={0}
                        className={line.budget.id === selectedId ? 'selected' : ''}
                        onFocus={() => setSelectedId(line.budget.id)}
                        onClick={() => setDialog({ kind: 'edit', line })}
                        onKeyDown={(e) => e.key === 'Enter' && setDialog({ kind: 'edit', line })}
                      >
                        <td>
                          {line.category.parent_id !== null ? `└ ${line.category.name}` : line.category.name}
                          <span className="show-sm">
                            <ProgressBar fraction={used} over={line.remaining < 0} />
                          </span>
                        </td>
                        <td className="num">{money.amount(line.budget.amount)}</td>
                        <td className="num hide-sm">
                          <Amount value={line.actual} money={money} />
                        </td>
                        <td className="num">
                          <Amount value={line.remaining} money={money} />
                        </td>
                        <td className="hide-sm">
                          <span className="progress-cell">
                            <ProgressBar fraction={used} over={line.remaining < 0} />
                            <span className="muted small">{Math.round(used * 100)}%</span>
                          </span>
                        </td>
                        <td className="actions" onClick={(e) => e.stopPropagation()}>
                          <RowMenu
                            actions={[
                              { label: 'Edit', onSelect: () => setDialog({ kind: 'edit', line }), shortcut: 'e' },
                              { label: 'Delete', onSelect: () => void deleteBudget(line), danger: true, shortcut: 'd' },
                            ]}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {report.data ? (
                <div className="totals">
                  <span>
                    Budget <strong>{money.amount(report.data.total_budget)}</strong>
                  </span>
                  <span>
                    Actual <Amount value={report.data.total_actual} money={money} />
                  </span>
                  <span>
                    Remaining <Amount value={report.data.total_remaining} money={money} bold />
                  </span>
                </div>
              ) : null}
            </div>
          )}
        </>
      )}
      {dialog?.kind === 'edit' && current ? (
        <BudgetForm periodId={current.id} line={dialog.line} onClose={() => setDialog(null)} categoriesInUse={lines} />
      ) : null}
      {dialog?.kind === 'copy' && current ? (
        <CopyBudgets target={current} periods={ordered} onClose={() => setDialog(null)} />
      ) : null}
    </div>
  );
}

function BudgetForm({
  periodId,
  line,
  onClose,
  categoriesInUse,
}: {
  periodId: number;
  line: BudgetLine | null;
  onClose: () => void;
  categoriesInUse: BudgetLine[];
}) {
  const money = useMoney();
  const categories = useCategories();
  const [categoryId, setCategoryId] = useState<number | null>(line?.category.id ?? null);
  const [amount, setAmount] = useState(line ? money.plain(line.budget.amount) : '');
  const taken = new Set(categoriesInUse.map((l) => l.category.id));
  const options = categoryTree(categories.data ?? []).map((c) => ({
    value: c.id,
    label: c.parent_id !== null ? `   └ ${c.name}` : c.name,
    disabled: taken.has(c.id) && c.id !== line?.category.id,
  }));
  const save = useApiMutation(async (api) => {
    const category_id = requiredId(categoryId, 'a category');
    if (!amount.trim()) throw new InputError('an amount is required');
    const value = money.parse(amount);
    if (line) {
      return unwrap(
        api.PATCH('/api/v1/budgets/{budget_id}', {
          params: { path: { budget_id: line.budget.id } },
          body: { category_id, amount: value },
        }),
      );
    }
    return unwrap(api.POST('/api/v1/budgets', { body: { category_id, period_id: periodId, amount: value } }));
  });
  return (
    <FormDialog
      open
      onClose={onClose}
      title={line ? `Budget for ${line.category.name}` : 'New budget'}
      onSubmit={() => save.mutateAsync(undefined)}
      help="A budget on a top-level category also covers its subcategories."
    >
      <SelectField label="Category" value={categoryId} options={options} onChange={setCategoryId} />
      <AmountField label="Amount" value={amount} onChange={setAmount} />
    </FormDialog>
  );
}

function CopyBudgets({ target, periods, onClose }: { target: Period; periods: Period[]; onClose: () => void }) {
  const sources = periods.filter((p) => p.id !== target.id);
  const before = [...sources].reverse().find((p) => p.start < target.start);
  const [source, setSource] = useState<number | null>(before?.id ?? sources[0]?.id ?? null);
  const [overwrite, setOverwrite] = useState<'no' | 'yes'>('no');
  const copy = useApiMutation((api) =>
    unwrap(
      api.POST('/api/v1/budgets/copy', {
        body: {
          source_period_id: requiredId(source, 'a period'),
          target_period_id: target.id,
          overwrite: overwrite === 'yes',
        },
      }),
    ),
  );
  return (
    <FormDialog open onClose={onClose} title={`Copy budgets into ${target.name}`} saveLabel="Copy" onSubmit={() => copy.mutateAsync(undefined)}>
      <SelectField
        label="From period"
        value={source}
        options={sources.map((p) => ({ value: p.id, label: `${p.name} (${periodRange(p)})` }))}
        onChange={setSource}
      />
      <SelectField
        label="Existing budgets"
        value={overwrite}
        options={[
          { value: 'no', label: 'Keep' },
          { value: 'yes', label: 'Overwrite' },
        ]}
        onChange={setOverwrite}
      />
    </FormDialog>
  );
}
