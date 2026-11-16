import { describe, expect, it } from 'vitest';
import { accountTarget, etaLabel, targetEta } from './goals';

describe('accountTarget', () => {
  it('measures a goal from zero', () => {
    expect(accountTarget(10_000, 2_500, null)).toEqual({ target: 10_000, fraction: 0.25 });
  });

  it('measures a debt from its lowest point toward zero', () => {
    expect(accountTarget(null, -3_000, -12_000)).toEqual({ target: 0, fraction: 0.75 });
    expect(accountTarget(0, -12_000, -12_000)).toEqual({ target: 0, fraction: 0 });
  });

  it('prefers the goal over the debt', () => {
    expect(accountTarget(1_000, -500, -500)).toEqual({ target: 1_000, fraction: -0.5 });
  });

  it('has no target without goal or debt', () => {
    expect(accountTarget(null, 500, null)).toBeNull();
    expect(accountTarget(null, -500, null)).toBeNull();
  });
});

describe('targetEta', () => {
  it('counts whole months after the current one', () => {
    expect(targetEta(-3_000, 0, 1_000, '2026-11-16')).toEqual({ kind: 'month', year: 2027, month: 2 });
    expect(targetEta(-2_500, 0, 1_000, '2026-11-16')).toEqual({ kind: 'month', year: 2027, month: 2 });
    expect(targetEta(9_000, 10_000, 1_000, '2026-12-01')).toEqual({ kind: 'month', year: 2027, month: 1 });
  });

  it('knows when the target is reached', () => {
    expect(targetEta(10_000, 10_000, null, '2026-11-16')).toEqual({ kind: 'reached' });
  });

  it('has no forecast without history, or when not getting closer', () => {
    expect(targetEta(-3_000, 0, null, '2026-11-16')).toEqual({ kind: 'unknown' });
    expect(targetEta(-3_000, 0, 0, '2026-11-16')).toEqual({ kind: 'never' });
    expect(targetEta(-3_000, 0, -100, '2026-11-16')).toEqual({ kind: 'never' });
    expect(targetEta(-1_000_000, 0, 1, '2026-11-16')).toEqual({ kind: 'never' });
  });
});

describe('etaLabel', () => {
  it('shows the month and year', () => {
    expect(etaLabel({ kind: 'month', year: 2027, month: 3 })).toBe('Mar 2027');
    expect(etaLabel({ kind: 'reached' })).toBe('reached');
    expect(etaLabel({ kind: 'unknown' })).toBe('');
  });
});
