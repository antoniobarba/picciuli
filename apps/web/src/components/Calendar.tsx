import { useEffect, useRef, type KeyboardEvent, type TouchEvent } from 'react';
import type { Period } from '../api/types';
import { covers, monthGrid, type DayFlow } from '../lib/calendar';
import { addDays, longDate, monthTitle, parts, WEEKDAY_SHORT, type Day } from '../lib/dates';
import type { MoneyFormat } from '../lib/money';

export interface CalendarProps {
  day: Day;
  today: Day;
  flows: ReadonlyMap<Day, DayFlow>;
  period: Period | null;
  money: MoneyFormat;
  onSelect: (day: Day) => void;
  onMonth: (step: number) => void;
  autoFocus?: boolean;
}

const STEPS: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };

/**
 * The month calendar of the overview: each day shows its net flow, `↔` marks
 * days with only transfers, and the selected period is drawn as a band.
 */
export function Calendar({ day, today, flows, period, money, onSelect, onMonth, autoFocus }: CalendarProps) {
  const { year, month } = parts(day);
  const grid = monthGrid(year, month);
  const gridRef = useRef<HTMLDivElement>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const focusSelected = useRef(Boolean(autoFocus));

  useEffect(() => {
    const element = gridRef.current;
    if (!element) return;
    if (focusSelected.current || element.contains(document.activeElement)) {
      element.querySelector<HTMLElement>('[aria-selected="true"]')?.focus({ preventScroll: true });
      focusSelected.current = false;
    }
  }, [day]);

  const onKeyDown = (event: KeyboardEvent) => {
    const step = STEPS[event.key];
    if (step !== undefined && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      onSelect(addDays(day, step));
    } else if (event.key === 'Home') {
      event.preventDefault();
      onSelect(addDays(day, -((grid.flat().indexOf(day) % 7))));
    } else if (event.key === 'End') {
      event.preventDefault();
      onSelect(addDays(day, 6 - (grid.flat().indexOf(day) % 7)));
    }
  };

  const onTouchStart = (event: TouchEvent) => {
    const point = event.touches[0];
    touch.current = point ? { x: point.clientX, y: point.clientY } : null;
  };
  const onTouchEnd = (event: TouchEvent) => {
    const start = touch.current;
    const point = event.changedTouches[0];
    touch.current = null;
    if (!start || !point) return;
    const dx = point.clientX - start.x;
    const dy = point.clientY - start.y;
    if (Math.abs(dx) > 60 && Math.abs(dy) < 50) onMonth(dx < 0 ? 1 : -1);
  };

  return (
    <section className="calendar" aria-label="Calendar">
      <div className="calendar-nav">
        <button type="button" className="icon-button" onClick={() => onMonth(-1)} aria-label="Previous month">
          ‹
        </button>
        <h2 aria-live="polite">{monthTitle(year, month)}</h2>
        <button type="button" className="icon-button" onClick={() => onMonth(1)} aria-label="Next month">
          ›
        </button>
        <button type="button" className="button small" onClick={() => onSelect(today)} disabled={day === today}>
          Today
        </button>
      </div>
      <div
        className="calendar-grid"
        role="grid"
        aria-label={monthTitle(year, month)}
        ref={gridRef}
        onKeyDown={onKeyDown}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        <div className="calendar-row calendar-head" role="row">
          {WEEKDAY_SHORT.map((name) => (
            <div key={name} role="columnheader" className="weekday">
              {name}
            </div>
          ))}
        </div>
        {grid.map((week) => (
          <div className="calendar-row" role="row" key={week[0]}>
            {week.map((cell) => {
              const flow = flows.get(cell);
              const inPeriod = period !== null && covers(period, cell);
              const classes = ['day'];
              if (parts(cell).month !== month) classes.push('outside');
              if (cell === day) classes.push('selected');
              if (cell === today) classes.push('today');
              if (inPeriod) classes.push('in-period');
              if (inPeriod && cell === period.start) classes.push('period-start');
              if (inPeriod && cell === period.end) classes.push('period-end');
              let label = longDate(cell);
              if (flow) {
                label += flow.transfersOnly
                  ? `, transfers only`
                  : `, net ${money.amount(flow.net, { plus: true })}, ${flow.count} transaction${flow.count === 1 ? '' : 's'}`;
              }
              return (
                <div role="gridcell" key={cell} className="day-cell">
                  <button
                    type="button"
                    className={classes.join(' ')}
                    tabIndex={cell === day ? 0 : -1}
                    aria-selected={cell === day}
                    aria-label={label}
                    aria-current={cell === today ? 'date' : undefined}
                    onClick={() => onSelect(cell)}
                  >
                    <span className="day-number">{parts(cell).day}</span>
                    {flow ? (
                      flow.transfersOnly && flow.net === 0 ? (
                        <span className="flow muted">↔</span>
                      ) : (
                        <span className={`flow ${flow.net < 0 ? 'negative' : flow.net > 0 ? 'positive' : 'muted'}`}>
                          {money.compact(flow.net)}
                        </span>
                      )
                    ) : null}
                    {flow ? <span className="dot" aria-hidden="true" /> : null}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
