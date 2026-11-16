/** Debts: account types, debt terms drafts, payoff labels and planner choices. */

import type { Account, AccountType, DebtChargeIn, DebtTermsIn, Rollover } from '../api/types';
import { monthName, parts, type Day } from './dates';
import { InputError, NONE_ID, optionalAmount } from './forms';
import { parseDecimal, type MoneyFormat } from './money';

export const LIABILITY_TYPES: ReadonlySet<AccountType> = new Set([
  'credit_card',
  'loan',
  'mortgage',
  'other_liability',
]);

export function isLiability(type: AccountType): boolean {
  return LIABILITY_TYPES.has(type);
}

export function isCard(type: AccountType): boolean {
  return type === 'credit_card';
}

/** Liabilities whose payments divide into principal and interest. */
export function isLoan(type: AccountType): boolean {
  return isLiability(type) && !isCard(type);
}

/** The balance of a liability typed as "how much do you owe": owing 150 is -150. */
export function balanceFromOwed(owed: number): number {
  return owed === 0 ? 0 : -owed;
}

/** The text of "how much do you owe" for a liability balance (negative while owed). */
export function owedText(balance: number, money: MoneyFormat): string {
  return money.plain(balance === 0 ? 0 : -balance);
}

/** Choice value of the interest category that creates a new category. */
export const NEW_CATEGORY = -1;

/** Most fixed charges of a loan, as the API accepts. */
export const MAX_CHARGES = 10;

/** A fixed charge included in every loan payment, as typed. */
export interface ChargeDraft {
  label: string;
  amount: string;
  /** A category, or `NONE_ID` for none. */
  categoryId: number;
}

export function emptyChargeDraft(): ChargeDraft {
  return { label: '', amount: '', categoryId: NONE_ID };
}

export interface TermsDraft {
  /** Whether the account has terms at all. */
  enabled: boolean;
  rate: string;
  payment: string;
  percent: string;
  dueDay: string;
  statementDay: string;
  creditLimit: string;
  /** `NONE_ID` for none. */
  paymentAccountId: number;
  /** A category, `NONE_ID` for none, or `NEW_CATEGORY` to create `newCategory`. */
  interestCategoryId: number;
  newCategory: string;
  proposeInterest: boolean;
  proposeMinimum: boolean;
  /** Loans only: fixed charges such as an insurance premium. */
  charges: ChargeDraft[];
}

/** The suggested name of the interest category of a new debt. */
export function interestCategoryName(accountName: string): string {
  return `${accountName.trim() || 'Debt'} interest`;
}

export function emptyTermsDraft(): TermsDraft {
  return {
    enabled: false,
    rate: '',
    payment: '',
    percent: '',
    dueDay: '',
    statementDay: '',
    creditLimit: '',
    paymentAccountId: NONE_ID,
    interestCategoryId: NEW_CATEGORY,
    newCategory: '',
    proposeInterest: true,
    proposeMinimum: true,
    charges: [],
  };
}

export function termsDraftFromAccount(account: Account, money: MoneyFormat): TermsDraft {
  const terms = account.debt_terms;
  if (!terms) return emptyTermsDraft();
  return {
    enabled: true,
    rate: terms.annual_rate,
    payment: terms.payment != null ? money.plain(terms.payment) : '',
    percent: terms.payment_percent ?? '',
    dueDay: terms.due_day != null ? String(terms.due_day) : '',
    statementDay: terms.statement_day != null ? String(terms.statement_day) : '',
    creditLimit: terms.credit_limit != null ? money.plain(terms.credit_limit) : '',
    paymentAccountId: terms.payment_account_id ?? NONE_ID,
    interestCategoryId: terms.interest_category_id ?? NONE_ID,
    newCategory: '',
    proposeInterest: terms.propose_interest,
    proposeMinimum: terms.propose_minimum,
    charges: terms.charges.map((charge) => ({
      label: charge.label ?? '',
      amount: money.plain(charge.amount),
      categoryId: charge.category_id ?? NONE_ID,
    })),
  };
}

/** A percentage from 0 to `max`, as a plain decimal string. */
export function parsePercent(text: string, label: string, max = 1000): string {
  const value = parseDecimal(text.replace(/%\s*$/, ''), label);
  const number = Number(value);
  if (number < 0 || number > max) throw new InputError(`the ${label} must be between 0 and ${max}%`);
  if ((value.split('.')[1] ?? '').length > 8) throw new InputError(`the ${label} has too many decimals`);
  return value;
}

function optionalDay(text: string, label: string): number | null {
  const cleaned = text.trim();
  if (!cleaned) return null;
  const value = Number(cleaned);
  if (!/^\d+$/.test(cleaned) || value < 1 || value > 31) {
    throw new InputError(`the ${label} must be a day of the month from 1 to 31`);
  }
  return value;
}

function optionalPositive(text: string, money: MoneyFormat, label: string): number | null {
  const value = optionalAmount(text, money);
  if (value !== null && value <= 0) throw new InputError(`the ${label} must be positive`);
  return value;
}

/** The charges of a loan draft; rows left blank are dropped. */
function chargesBody(charges: readonly ChargeDraft[], payment: number | null, money: MoneyFormat): DebtChargeIn[] {
  const result = charges
    .filter((charge) => charge.amount.trim() || charge.label.trim())
    .map((charge) => {
      const name = charge.label.trim();
      const amount = optionalPositive(charge.amount, money, `amount of the ${name || 'fixed'} charge`);
      if (amount === null) throw new InputError(`enter the amount of the ${name || 'fixed'} charge`);
      return { amount, category_id: charge.categoryId === NONE_ID ? null : charge.categoryId, label: name || null };
    });
  const total = result.reduce((sum, charge) => sum + charge.amount, 0);
  if (payment !== null && result.length && total >= payment) {
    throw new InputError('the fixed charges must be less than the monthly payment');
  }
  return result;
}

/** The API terms of a draft, or `null` when the account has no terms. */
export function termsBody(draft: TermsDraft, type: AccountType, money: MoneyFormat): DebtTermsIn | null {
  if (!draft.enabled || !isLiability(type)) return null;
  const card = isCard(type);
  const body: DebtTermsIn = {
    annual_rate: parsePercent(draft.rate || '0', 'interest rate'),
    payment: optionalPositive(draft.payment, money, card ? 'minimum payment' : 'monthly payment'),
    due_day: optionalDay(draft.dueDay, 'due day'),
    payment_account_id: draft.paymentAccountId || null,
    interest_category_id:
      draft.interestCategoryId === NEW_CATEGORY || draft.interestCategoryId === NONE_ID
        ? null
        : draft.interestCategoryId,
    payment_percent: null,
    statement_day: null,
    credit_limit: null,
    propose_interest: false,
    propose_minimum: false,
    charges: [],
  };
  if (draft.interestCategoryId === NEW_CATEGORY) {
    const name = draft.newCategory.trim();
    if (!name) throw new InputError('name the new interest category');
    body.new_interest_category = name;
  }
  if (!card) body.charges = chargesBody(draft.charges, body.payment ?? null, money);
  if (card) {
    body.payment_percent = draft.percent.trim() ? parsePercent(draft.percent, 'minimum payment percent', 100) : null;
    body.statement_day = optionalDay(draft.statementDay, 'statement day');
    body.credit_limit = optionalPositive(draft.creditLimit, money, 'credit limit');
    body.propose_interest = draft.proposeInterest;
    body.propose_minimum = draft.proposeMinimum;
    if (draft.proposeInterest && (body.statement_day === null || draft.interestCategoryId === NONE_ID)) {
      throw new InputError('to propose interest charges, enter the statement day and an interest category');
    }
    if (
      draft.proposeMinimum &&
      (body.statement_day === null || body.due_day === null || (body.payment === null && body.payment_percent === null))
    ) {
      throw new InputError(
        'to propose minimum payments, enter the statement day, the due day and the minimum payment',
      );
    }
  }
  return body;
}

/** `Mar 2031`, or a dash when the debt is never paid off. */
export function payoffLabel(payoff: Day | null | undefined): string {
  if (!payoff) return '—';
  const { year, month } = parts(payoff);
  return `${monthName(month).slice(0, 3)} ${year}`;
}

/** `4 years 3 months`, `11 months`. */
export function durationLabel(months: number): string {
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const pieces = [];
  if (years) pieces.push(`${years} year${years === 1 ? '' : 's'}`);
  if (rest || !years) pieces.push(`${rest} month${rest === 1 ? '' : 's'}`);
  return pieces.join(' ');
}

export interface RolloverChoice {
  value: Rollover;
  label: string;
  pros: string;
  cons: string;
}

export const ROLLOVER_CHOICES: readonly RolloverChoice[] = [
  {
    value: 'full',
    label: 'Roll it into the next debt',
    pros: 'Fastest payoff and the least interest: the classic snowball or avalanche.',
    cons: 'Your monthly debt payments stay the same until every debt is gone.',
  },
  {
    value: 'none',
    label: 'Free it up',
    pros: 'More money every month as each debt closes.',
    cons: 'Slower payoff and more interest overall.',
  },
  {
    value: 'partial',
    label: 'Split it',
    pros: 'A share goes to the next debt, the rest is yours: a middle way.',
    cons: 'Neither the fastest payoff nor the most monthly cash.',
  },
];
