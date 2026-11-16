import { describe, expect, it } from 'vitest';
import { debtTarget, etaLabel, targetEta } from './goals';

describe('debtTarget', () => {
  it('measures a debt from its lowest point toward zero', () => {
    expect(debtTarget(-3_000, -12_000)).toEqual({ target: 0, fraction: 0.75 });
    expect(debtTarget(-12_000, -12_000)).toEqual({ target: 0, fraction: 0 });
  });

  it('has no target without a debt', () => {
    expect(debtTarget(500, null)).toBeNull();
    expect(debtTarget(-500, null)).toBeNull();
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
