import { describe, expect, it } from 'vitest';
import {
  formatAmount,
  InputError,
  MoneyFormat,
  parseAmount,
  parseDecimal,
  parsePrice,
  parseQuantity,
  percentText,
  priceText,
  quantityText,
  roundedPrice,
} from './money';

describe('formatAmount', () => {
  it('formats like picciuli.money', () => {
    expect(formatAmount(-123450, { currency: '€' })).toBe('-€1,234.50');
    expect(formatAmount(5, { digits: 3, plus: true })).toBe('+0.005');
    expect(formatAmount(-1_234_500, { currency: 'EUR', digits: 3 })).toBe('-EUR 1,234.500');
    expect(formatAmount(-1_234_500, { digits: 3, group: false })).toBe('-1234.500');
    expect(formatAmount(7, { currency: '¥', digits: 0 })).toBe('¥7');
  });
});

describe('parseAmount', () => {
  it.each([
    ['12', 1200],
    ['-1,234.5', -123450],
    ['+3.10', 310],
    ['12,50', 1250],
    ['1.234,56', 123456],
    ['1,000', 100000],
    ['1,234,567', 123456700],
    ['.5', 50],
    [' 7 ', 700],
  ])('parses %s', (text, expected) => {
    expect(parseAmount(text)).toBe(expected);
  });

  it('keeps grouped thousands with three minor digits', () => {
    expect(parseAmount('1,000', 3)).toBe(1_000_000);
  });

  it.each(['', 'abc', '1.2.3', '--1', '.', '1.234', '1,2,3'])('rejects %s', (text) => {
    expect(() => parseAmount(text)).toThrow(InputError);
  });
});

describe('MoneyFormat.compact', () => {
  it.each([
    [0, '+0'],
    [-4530, '-45'],
    [250, '+2.5'],
    [-99_950, '-1k'],
    [-99_949, '-999'],
    [245_000, '+2.5k'],
    [1_234_500, '+12k'],
    [-999_960_00, '-1M'],
    [123_456_789_00, '+123M'],
    [1_234_567_890_00, '+1.2G'],
    [999_999_999_999_00, '+1000G'],
  ])('compacts %d to %s', (amount, expected) => {
    expect(new MoneyFormat().compact(amount)).toBe(expected);
  });

  it('rounds to units without minor digits', () => {
    expect(new MoneyFormat('¥', 0).compact(7)).toBe('+7');
  });
});

describe('decimals', () => {
  it.each([
    ['1.5', '1.5'],
    ['1,5', '1.5'],
    ['1,234.5', '1234.5'],
    ['1.234,5', '1234.5'],
    [' 2 ', '2'],
  ])('parses %s', (text, expected) => {
    expect(parseDecimal(text, 'quantity')).toBe(expected);
  });

  it.each(['', 'abc', 'inf', '1,2,3'])('rejects %s', (text) => {
    expect(() => parseDecimal(text, 'quantity')).toThrow(InputError);
  });

  it('checks quantities and prices', () => {
    expect(parseQuantity('-2', true)).toBe('-2');
    expect(() => parseQuantity('0')).toThrow('positive');
    expect(() => parseQuantity('-1')).toThrow('positive');
    expect(parsePrice('169,86')).toBe('169.86');
    expect(() => parsePrice('-1')).toThrow('positive');
  });

  it('formats quantities and prices', () => {
    expect(quantityText('1234.5000')).toBe('1,234.5');
    expect(quantityText('3')).toBe('3');
    expect(priceText('169.8', 'EUR')).toBe('169.80 EUR');
    expect(priceText('0.123456', 'USD')).toBe('0.123456 USD');
    expect(priceText('1200', 'USD')).toBe('1,200.00 USD');
    expect(roundedPrice('169.8649')).toBe('169.86');
    expect(roundedPrice('0.123456')).toBe('0.1235');
  });

  it('formats percentages', () => {
    expect(percentText(125, 1000)).toBe('+12.5%');
    expect(percentText(-50, -1000)).toBe('-5.0%');
    expect(percentText(1, 0)).toBe('');
  });
});
