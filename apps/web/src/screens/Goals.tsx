import { useState } from 'react';
import { Link } from 'react-router';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useGoalReport, useMoney } from '../api/queries';
import type { Goal, GoalAccount, GoalProgress } from '../api/types';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import { Amount, Empty, Loading, PageHeader, ProgressBar } from '../components/ui';
import { GoalForm } from '../forms/GoalForm';
import { shortDate, todayDay } from '../lib/dates';
import { canHoldGoals, PRIORITY_LABELS, savedFraction } from '../lib/goals';
import type { MoneyFormat } from '../lib/money';
import { useHotkeys } from '../lib/useHotkeys';

type Dialog = { goal: Goal | null; accountId?: number } | null;

export function Goals() {
  const money = useMoney();
  const today = todayDay();
  const report = useGoalReport(today);
  const accounts = useAccounts(false);
  const confirm = useConfirm();
  const notify = useNotify();
  const [dialog, setDialog] = useState<Dialog>(null);
  const canAdd = (accounts.data ?? []).some((a) => canHoldGoals(a.type));

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/goals/{goal_id}', { params: { path: { goal_id: id } } })),
  );
  const deleteGoal = async (goal: Goal) => {
    const ok = await confirm({
      title: `Delete “${goal.name}”?`,
      message: 'The money stays in the account; only the goal is removed.',
    });
    if (!ok) return;
    try {
      await remove.mutateAsync(goal.id);
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
    }
  };

  useHotkeys({ n: () => canAdd && setDialog({ goal: null }) });

  const groups = report.data?.accounts ?? [];
  let content;
  if (report.isLoading || accounts.isLoading) {
    content = <Loading />;
  } else if (report.isError || accounts.isError) {
    content = (
      <Empty>
        <p>The goals could not be loaded.</p>
        <button
          type="button"
          className="button primary"
          onClick={() => void Promise.all([report.refetch(), accounts.refetch()])}
        >
          Try again
        </button>
      </Empty>
    );
  } else if (!groups.length) {
    content = canAdd ? (
      <Empty>
        <p>
          Save for an emergency fund, a holiday or a car: set a target, an optional date and a priority, and Picciuli
          shows how much to put aside every month. One account can hold several goals.
        </p>
        <button type="button" className="button primary" onClick={() => setDialog({ goal: null })}>
          + New goal
        </button>
      </Empty>
    ) : (
      <Empty>
        <p>Goals live in a checking, savings, cash or other asset account. Create one first.</p>
        <Link to="/accounts" className="button primary">
          Go to Accounts
        </Link>
      </Empty>
    );
  } else {
    content = groups.map((group) => (
      <AccountGoals
        key={group.account.id}
        group={group}
        money={money}
        onAdd={() => setDialog({ goal: null, accountId: group.account.id })}
        onEdit={(goal) => setDialog({ goal })}
        onDelete={(goal) => void deleteGoal(goal)}
      />
    ));
  }

  return (
    <div className="page">
      <PageHeader title="Savings goals">
        {canAdd ? (
          <button type="button" className="button primary" onClick={() => setDialog({ goal: null })}>
            + New goal
          </button>
        ) : null}
      </PageHeader>
      {content}
      {dialog ? <GoalForm goal={dialog.goal} accountId={dialog.accountId} onClose={() => setDialog(null)} /> : null}
    </div>
  );
}

function AccountGoals({
  group,
  money,
  onAdd,
  onEdit,
  onDelete,
}: {
  group: GoalAccount;
  money: MoneyFormat;
  onAdd: () => void;
  onEdit: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
}) {
  const { account } = group;
  return (
    <section className="goal-account" aria-label={account.name}>
      <div className="goal-account-header">
        <h2>
          <Link to={`/accounts/${account.id}`}>{account.name}</Link>
          {account.is_closed ? <small className="muted"> closed</small> : null}
        </h2>
        <span className="goal-account-totals">
          <span>
            Balance <Amount value={group.balance} money={money} />
          </span>
          <span>
            Assigned <Amount value={group.assigned} money={money} muted />
          </span>
          <span>
            Unassigned <Amount value={group.unassigned} money={money} />
          </span>
        </span>
        {account.is_closed ? null : (
          <button type="button" className="button small" onClick={onAdd}>
            + Goal
          </button>
        )}
      </div>
      {group.shortfall > 0 ? (
        <p className="goal-warning" role="status">
          These goals claim {money.amount(group.shortfall)} more than the account holds. Move money into{' '}
          {account.name} or lower the saved amounts.
        </p>
      ) : null}
      <div className="debt-grid">
        {group.goals.map((progress) => (
          <GoalCard
            key={progress.goal.id}
            progress={progress}
            money={money}
            onEdit={() => onEdit(progress.goal)}
            onDelete={() => onDelete(progress.goal)}
          />
        ))}
      </div>
    </section>
  );
}

function monthlyText(progress: GoalProgress, money: MoneyFormat): string {
  switch (progress.status) {
    case 'reached':
      return 'Reached';
    case 'undated':
      return 'Add a target date to plan it';
    case 'overdue':
      return `Overdue: ${money.amount(progress.remaining)} still missing`;
    case 'scheduled': {
      const months = progress.months_left ?? 1;
      return `${money.amount(progress.monthly_amount ?? 0)} a month · ${months} ${months === 1 ? 'month' : 'months'}`;
    }
  }
}

function GoalCard({
  progress,
  money,
  onEdit,
  onDelete,
}: {
  progress: GoalProgress;
  money: MoneyFormat;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { goal } = progress;
  const fraction = savedFraction(goal);
  return (
    <section className={`card goal-card ${progress.status}`} aria-label={goal.name}>
      <div className="card-header">
        <h3>{goal.name}</h3>
        <span className={`priority-pill ${goal.priority}`}>{PRIORITY_LABELS[goal.priority]}</span>
      </div>
      <div className="goal-progress">
        <ProgressBar fraction={fraction} />
        <span>
          <Amount value={goal.saved_amount} money={money} bold /> of {money.amount(goal.target_amount)}
          <span className="muted small"> · {Math.round(fraction * 100)}%</span>
        </span>
      </div>
      <dl className="facts">
        <dt>Remaining</dt>
        <dd>{money.amount(progress.remaining)}</dd>
        <dt>Target date</dt>
        <dd>{goal.target_date ? shortDate(goal.target_date) : 'None'}</dd>
        <dt>To save</dt>
        <dd className={progress.status === 'overdue' ? 'goal-overdue' : undefined}>{monthlyText(progress, money)}</dd>
      </dl>
      <div className="debt-actions">
        <button type="button" className="button small" onClick={onEdit}>
          Edit
        </button>
        <button type="button" className="button small danger-text" onClick={onDelete}>
          Delete
        </button>
      </div>
    </section>
  );
}
