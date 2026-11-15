/**
 * Amounts are integers in minor units (cents), as in the library and the API.
 * These helpers mirror `picciuli.money` and the TUI's `MoneyFormat`, using
 * string arithmetic so that no floating-point rounding is ever involved.
 */

export class InputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InputError';
  }
}

export interface FormatOptions {
  currency?: string | null;
  digits?: number;
  plus?: boolean;
  group?: boolean;
}

function groupThousands(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** `formatAmount(-123450, {currency: '€'})` → `-€1,234.50`. */
export function formatAmount(amount: number, options: FormatOptions = {}): string {
  const { currency = null, digits = 2, plus = false, group = true } = options;
  const sign = amount < 0 ? '-' : plus && amount > 0 ? '+' : '';
  const text = Math.abs(Math.trunc(amount)).toString().padStart(digits + 1, '0');
  let integer = digits ? text.slice(0, -digits) : text;
  const fraction = digits ? text.slice(-digits) : '';
  if (group) integer = groupThousands(integer);
  const number = integer + (digits ? `.${fraction}` : '');
  let prefix = '';
  if (currency) prefix = currency + (/\p{L}$/u.test(currency) ? ' ' : '');
  return `${sign}${prefix}${number}`;
}

/**
 * Normalize typed numbers to a plain `-1234.5` form.
 *
 * Both `1,234.50` and `1.234,50` are understood: with both separators the
 * last one is the decimal separator. Commas followed by groups of exactly
 * three digits separate thousands when `commaGroups` is set (`1,234`);
 * otherwise a single comma is a decimal separator (`12,50`, as typed on many
 * phone keyboards). Anything else is left alone and rejected by the caller.
 */
export function normalizeNumber(text: string, commaGroups = true): string {
  let cleaned = text.trim().replace(/[\s'\u00a0\u202f]/g, '');
  const hasComma = cleaned.includes(',');
  const hasDot = cleaned.includes('.');
  if (hasComma && hasDot) {
    if (cleaned.lastIndexOf(',') > cleaned.lastIndexOf('.')) {
      cleaned = cleaned.replace(/\./g, '').replace(',', '.');
    } else {
      cleaned = cleaned.replace(/,/g, '');
    }
  } else if (hasComma) {
    if (commaGroups && /^[+-]?\d{1,3}(,\d{3})+$/.test(cleaned)) {
      cleaned = cleaned.replace(/,/g, '');
    } else if (cleaned.split(',').length === 2) {
      cleaned = cleaned.replace(',', '.');
    }
  }
  return cleaned;
}

/** Parse typed text into minor units; raises `InputError`, never rounds. */
export function parseAmount(text: string, digits = 2): number {
  const cleaned = normalizeNumber(text);
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(cleaned);
  if (!match || (!match[2] && !match[3])) throw new InputError(`invalid amount: '${text.trim()}'`);
  const [, sign, integer = '', rawFraction = ''] = match;
  const fraction = rawFraction.replace(/0+$/, '');
  if (fraction.length > digits) {
    throw new InputError(`amount cannot have more than ${digits} decimal digits`);
  }
  const minor = Number((integer || '0') + fraction.padEnd(digits, '0'));
  if (!Number.isSafeInteger(minor)) throw new InputError(`amount too large: '${text.trim()}'`);
  return sign === '-' && minor !== 0 ? -minor : minor;
}

const COMPACT_UNITS: [number, string][] = [
  [0, ''],
  [3, 'k'],
  [6, 'M'],
  [9, 'G'],
];

/** Round a non-negative decimal string half up to `places` decimals. */
export function roundDecimal(value: string, places: number): string {
  const negative = value.startsWith('-');
  const [integer = '0', fraction = ''] = value.replace(/^[+-]/, '').split('.');
  const digits = (integer + fraction.padEnd(places + 1, '0').slice(0, places + 1)).replace(/^0+(?=\d)/, '');
  const keep = BigInt(digits.slice(0, -1) || '0') + (Number(digits.slice(-1)) >= 5 ? 1n : 0n);
  let text = keep.toString().padStart(places + 1, '0');
  if (places) text = `${text.slice(0, -places)}.${text.slice(-places)}`;
  return negative && /[1-9]/.test(text) ? `-${text}` : text;
}

function stripZeros(text: string): string {
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text;
}

/** Shift a non-negative decimal string left by `exponent` places (divide by 10^exponent). */
function scaleDown(integerDigits: string, exponent: number): string {
  if (exponent <= 0) return integerDigits;
  const padded = integerDigits.padStart(exponent + 1, '0');
  return `${padded.slice(0, -exponent)}.${padded.slice(-exponent)}`;
}

export class MoneyFormat {
  constructor(
    readonly currency = '$',
    readonly digits = 2,
  ) {}

  /** `-$1,234.50` */
  amount(value: number, options: { currency?: boolean; plus?: boolean } = {}): string {
    return formatAmount(value, {
      currency: options.currency === false ? null : this.currency,
      digits: this.digits,
      plus: options.plus ?? false,
    });
  }

  /** Editable text without currency or grouping, e.g. `-1234.50`. */
  plain(value: number): string {
    return formatAmount(value, { digits: this.digits, group: false });
  }

  parse(text: string): number {
    return parseAmount(text, this.digits);
  }

  /** A signed amount in at most six characters, e.g. `-45` or `+2.1k`. */
  compact(value: number): string {
    const sign = value < 0 ? '-' : '+';
    const minor = Math.abs(Math.trunc(value)).toString();
    let text = '0';
    let suffix = '';
    for (const [power, unit] of COMPACT_UNITS) {
      suffix = unit;
      const scaled = scaleDown(minor, this.digits + power);
      const integerPart = scaled.split('.')[0] ?? '0';
      const places = integerPart.replace(/^0+/, '').length <= 1 && (unit || this.digits) ? 1 : 0;
      text = roundDecimal(scaled, places);
      const rounded = text.split('.')[0] ?? '0';
      if (rounded.length < 4 || unit === 'G') break;
    }
    return `${sign}${stripZeros(text)}${suffix}`;
  }
}

/** Parse a typed decimal such as `1.5`, `1,5` or `1,234.5` into a plain string. */
export function parseDecimal(text: string, label: string): string {
  if (!text.trim()) throw new InputError(`${label} is required`);
  const cleaned = normalizeNumber(text, false);
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(cleaned)) {
    throw new InputError(`invalid ${label}: '${text.trim()}'`);
  }
  let result = cleaned.replace(/^\+/, '');
  if (result.startsWith('.')) result = `0${result}`;
  if (result.startsWith('-.')) result = `-0${result.slice(1)}`;
  return result.endsWith('.') ? result.slice(0, -1) : result;
}

function isZero(decimal: string): boolean {
  return !/[1-9]/.test(decimal);
}

export function parseQuantity(text: string, signed = false): string {
  const value = parseDecimal(text, 'quantity');
  if (isZero(value) || (value.startsWith('-') && !signed)) {
    throw new InputError('enter a positive quantity');
  }
  return value;
}

export function parsePrice(text: string): string {
  const value = parseDecimal(text, 'price');
  if (isZero(value) || value.startsWith('-')) throw new InputError('enter a positive price');
  return value;
}

/** A number of shares without useless zeros, e.g. `1,234.5`. */
export function quantityText(value: string): string {
  const negative = value.startsWith('-');
  const [integer = '0', fraction = ''] = value.replace(/^[+-]/, '').split('.');
  const trimmed = fraction.replace(/0+$/, '');
  const text = groupThousands(integer.replace(/^0+(?=\d)/, '')) + (trimmed ? `.${trimmed}` : '');
  return negative ? `-${text}` : text;
}

/** A price with at least two decimals, e.g. `169.86 EUR`. */
export function priceText(value: string, currency: string): string {
  const [integer = '0', fraction = ''] = value.replace(/^[+-]/, '').split('.');
  const trimmed = fraction.replace(/0+$/, '');
  const decimals = trimmed.padEnd(2, '0');
  const sign = value.startsWith('-') ? '-' : '';
  return `${sign}${groupThousands(integer.replace(/^0+(?=\d)/, ''))}.${decimals} ${currency}`.trim();
}

/** Round a computed price for display: 2 decimals, 4 below one unit. */
export function roundedPrice(value: string): string {
  const integer = value.replace(/^[+-]/, '').split('.')[0] ?? '0';
  return roundDecimal(value, Number(integer) >= 1 ? 2 : 4);
}

/** `part / whole` as a signed percentage such as `+12.5%`, or ''. */
export function percentText(part: number, whole: number): string {
  if (!whole) return '';
  const value = (part / Math.abs(whole)) * 100;
  const text = value.toFixed(1);
  return `${value >= 0 && !text.startsWith('-') ? '+' : ''}${text}%`;
}
