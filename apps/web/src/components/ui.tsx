import * as Menu from '@radix-ui/react-dropdown-menu';
import type { KeyboardEvent, ReactNode } from 'react';
import type { MoneyFormat } from '../lib/money';

/**
 * `onKeyDown` for a focusable row: Enter on the row itself (not on its handle
 * or menu) opens it. The key is consumed so that it does not also press a
 * button in the dialog the row opens.
 */
export function onEnter(open: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Enter' || event.target !== event.currentTarget) return;
    event.preventDefault();
    open();
  };
}

export function Amount({
  value,
  money,
  plus = false,
  bold = false,
  muted = false,
}: {
  value: number;
  money: MoneyFormat;
  plus?: boolean;
  bold?: boolean;
  muted?: boolean;
}) {
  const tone = muted ? 'muted' : value < 0 ? 'negative' : value > 0 ? 'positive' : 'zero';
  return <span className={`amount ${tone}${bold ? ' bold' : ''}`}>{money.amount(value, { plus })}</span>;
}

export function ProgressBar({ fraction, over = false }: { fraction: number; over?: boolean }) {
  const clamped = Math.min(Math.max(fraction, 0), 1);
  return (
    <span className={`progress${over ? ' over' : ''}`} role="progressbar" aria-valuenow={Math.round(clamped * 100)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${clamped * 100}%` }} />
    </span>
  );
}

export interface MenuAction {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  shortcut?: string;
}

/** The "⋯" menu of a row. */
export function RowMenu({ actions, label = 'Actions' }: { actions: readonly (MenuAction | null | false)[]; label?: string }) {
  const items = actions.filter((action): action is MenuAction => Boolean(action));
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger className="icon-button row-menu" aria-label={label} onClick={(e) => e.stopPropagation()}>
        ⋯
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="menu" align="end" sideOffset={4} onClick={(e) => e.stopPropagation()}>
          {items.map((action) => (
            <Menu.Item
              key={action.label}
              className={`menu-item${action.danger ? ' danger' : ''}`}
              disabled={action.disabled}
              onSelect={action.onSelect}
            >
              <span>{action.label}</span>
              {action.shortcut ? <kbd>{action.shortcut}</kbd> : null}
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() {
  return (
    <div className="loading" aria-busy="true">
      Loading…
    </div>
  );
}

export function PageHeader({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      <div className="toolbar">{children}</div>
    </div>
  );
}
