import { Modal } from '../components/Modal';

const SECTIONS: [string, [string, string][]][] = [
  [
    'Everywhere',
    [
      ['1 … 6', 'Overview, Accounts, Categories, Periods, Budgets, Investments'],
      ['s', 'Settings'],
      ['ctrl+k', 'Command palette'],
      ['l', 'Live prices on/off'],
      ['?', 'This help'],
      ['n / e / d', 'New / edit / delete the selected item'],
      ['enter', 'Open or edit the focused row'],
      ['ctrl+s', 'Save the open form'],
      ['esc', 'Close the dialog'],
    ],
  ],
  [
    'Overview',
    [
      ['← → ↑ ↓', 'Previous / next day, previous / next week (calendar focused)'],
      ['pgup pgdn', 'Previous / next month (or swipe the calendar)'],
      ['t', 'Today'],
      ['g', 'Go to a date'],
      ['[ ]', 'Previous / next period covering the day'],
      ['p', 'Start a period on the selected day'],
    ],
  ],
  [
    'Lists',
    [
      ['shift+↑ ↓', 'Move the account or category up / down'],
      ['⠿ alt+↑ ↓', 'On a drag handle: move the row up / down'],
      ['⠿ space ↑ ↓ space', 'On a drag handle: pick the row up, choose its place, drop it (esc cancels)'],
      ['c', 'Close or reopen the account'],
      ['[ ] y', 'Budgets: change period, copy budgets from another period'],
    ],
  ],
  [
    'Investments',
    [
      ['f', 'Find a security online'],
      ['b / x', 'Buy / sell shares'],
      ['p', 'Enter a price by hand'],
      ['r / h', 'Refresh prices / download the price history'],
    ],
  ],
];

export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Keyboard shortcuts" wide>
      <div className="form-body help">
        <p className="muted">
          Dates can be typed as 2025-02-03, 3/2/2025, 3/2 (this year), 3 (this month), today, or offsets such as +1
          and -7. Amounts accept 1,234.50 as well as 1.234,50.
        </p>
        {SECTIONS.map(([title, keys]) => (
          <section key={title}>
            <h3>{title}</h3>
            <dl className="keys">
              {keys.map(([key, action]) => (
                <div key={key}>
                  <dt>
                    <kbd>{key}</kbd>
                  </dt>
                  <dd>{action}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  );
}
