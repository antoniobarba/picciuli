import { describe, expect, it } from 'vitest';
import {
  balanceFromOwed,
  durationLabel,
  emptyTermsDraft,
  NEW_CATEGORY,
  owedText,
  parsePercent,
  payoffLabel,
  termsBody,
} from './debts';
import { NONE_ID } from './forms';
import { MoneyFormat } from './money';

const money = new MoneyFormat('€', 2);

describe('owed amounts', () => {
  it('turns what you owe into a negative balance and back', () => {
    expect(balanceFromOwed(150000)).toBe(-150000);
    expect(balanceFromOwed(0)).toBe(0);
    expect(owedText(-150000, money)).toBe('1500.00');
    expect(owedText(0, money)).toBe('0.00');
  });
});

describe('termsBody', () => {
  const card = {
    ...emptyTermsDraft(),
    enabled: true,
    rate: '19,9',
    percent: '3%',
    payment: '25',
    dueDay: '15',
    statementDay: '1',
    newCategory: 'Visa interest',
  };

  it('builds the terms of a credit card with a new interest category', () => {
    expect(termsBody(card, 'credit_card', money)).toEqual({
      annual_rate: '19.9',
      payment: 2500,
      payment_percent: '3',
      due_day: 15,
      statement_day: 1,
      credit_limit: null,
      payment_account_id: null,
      interest_category_id: null,
      new_interest_category: 'Visa interest',
      propose_interest: true,
      propose_minimum: true,
    });
  });

  it('drops card fields from loans and returns null without terms', () => {
    const loan = termsBody({ ...card, interestCategoryId: 7 }, 'mortgage', money);
    expect(loan).toMatchObject({ statement_day: null, payment_percent: null, propose_minimum: false });
    expect(loan?.interest_category_id).toBe(7);
    expect(termsBody({ ...card, enabled: false }, 'loan', money)).toBeNull();
    expect(termsBody(card, 'checking', money)).toBeNull();
  });

  it('explains what proposals need', () => {
    expect(() => termsBody({ ...card, statementDay: '' }, 'credit_card', money)).toThrow(/statement day/);
    expect(() =>
      termsBody({ ...card, interestCategoryId: NONE_ID, proposeMinimum: false }, 'credit_card', money),
    ).toThrow(/interest category/);
    expect(() => termsBody({ ...card, dueDay: '32' }, 'credit_card', money)).toThrow(/1 to 31/);
    expect(() => termsBody({ ...card, interestCategoryId: NEW_CATEGORY, newCategory: ' ' }, 'loan', money)).toThrow(
      /name the new interest category/,
    );
  });
});

describe('labels', () => {
  it('formats percentages, payoff months and durations', () => {
    expect(parsePercent('4,25 %', 'rate')).toBe('4.25');
    expect(() => parsePercent('2000', 'rate')).toThrow(/between 0 and 1000/);
    expect(payoffLabel('2031-03-01')).toBe('Mar 2031');
    expect(payoffLabel(null)).toBe('—');
    expect(durationLabel(51)).toBe('4 years 3 months');
    expect(durationLabel(24)).toBe('2 years');
    expect(durationLabel(1)).toBe('1 month');
  });
});
