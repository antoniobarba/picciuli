/**
 * Calendar days as ISO strings (`2025-02-03`), the format used by the API.
 *
 * Arithmetic goes through UTC dates so that time zones and daylight saving
 * never shift a day.
 */

export type Day = string;

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export const WEEKDAY_SHORT = WEEKDAYS.map((name) => name.slice(0, 3));

export function monthName(month: number): string {
  return MONTHS[month - 1] ?? '';
}

export function makeDay(year: number, month: number, day: number): Day {
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function parts(day: Day): { year: number; month: number; day: number } {
  const [year, month, date] = day.split('-').map(Number);
  return { year: year ?? 0, month: month ?? 0, day: date ?? 0 };
}

function toUtc(day: Day): Date {
  const { year, month, day: date } = parts(day);
  const result = new Date(Date.UTC(2000, month - 1, date));
  result.setUTCFullYear(year);
  return result;
}

function fromUtc(date: Date): Day {
  return makeDay(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(2000 + (year % 400), month, 0)).getUTCDate();
}

/** Whether `year`, `month`, `day` is a real calendar day. */
export function isValidDay(year: number, month: number, day: number): boolean {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return false;
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) return false;
  return day <= daysInMonth(year, month);
}

export function todayDay(now: Date = new Date()): Day {
  return makeDay(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

export function addDays(day: Day, days: number): Day {
  const date = toUtc(day);
  date.setUTCDate(date.getUTCDate() + days);
  return fromUtc(date);
}

/** Days from `a` to `b` (positive when `b` is later). */
export function daysBetween(a: Day, b: Day): number {
  return Math.round((toUtc(b).getTime() - toUtc(a).getTime()) / 86_400_000);
}

/** 0 for Monday … 6 for Sunday. */
export function weekday(day: Day): number {
  return (toUtc(day).getUTCDay() + 6) % 7;
}

/** `03 Feb 2025` */
export function shortDate(day: Day): string {
  const { year, month, day: date } = parts(day);
  return `${String(date).padStart(2, '0')} ${monthName(month).slice(0, 3)} ${year}`;
}

/** `Monday 03 February 2025` */
export function longDate(day: Day): string {
  const { year, month, day: date } = parts(day);
  return `${WEEKDAYS[weekday(day)]} ${String(date).padStart(2, '0')} ${monthName(month)} ${year}`;
}

/** `February 2025` */
export function monthTitle(year: number, month: number): string {
  return `${monthName(month)} ${year}`;
}
