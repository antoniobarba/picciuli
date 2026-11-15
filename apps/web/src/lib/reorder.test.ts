import { describe, expect, it } from 'vitest';
import { applyMove, dropIndex } from './reorder';

const item = (id: number, position: number, group = 0) => ({ id, position, group });
const order = (items: { id: number; position: number }[]) =>
  [...items].sort((a, b) => a.position - b.position).map((i) => i.id);

describe('applyMove', () => {
  it('reinserts the item at the position and renumbers its siblings', () => {
    const items = [item(1, 1), item(2, 2), item(3, 3), item(4, 4)];
    expect(order(applyMove(items, 1, 3))).toEqual([2, 3, 1, 4]);
    expect(order(applyMove(items, 4, 1))).toEqual([4, 1, 2, 3]);
    expect(applyMove(items, 4, 1).map((i) => i.position)).toEqual([2, 3, 4, 1]);
  });

  it('clamps the position and keeps unchanged items as they are', () => {
    const items = [item(1, 1), item(2, 2), item(3, 3)];
    expect(order(applyMove(items, 1, 99))).toEqual([2, 3, 1]);
    const moved = applyMove(items, 2, 0);
    expect(order(moved)).toEqual([2, 1, 3]);
    expect(moved[2]).toBe(items[2]);
  });

  it('only touches the siblings of the moved item', () => {
    const items = [item(1, 1, 1), item(2, 2, 1), item(3, 1, 2), item(4, 2, 2)];
    const moved = applyMove(items, 4, 1, (a, b) => a.group === b.group);
    expect(moved.map((i) => i.position)).toEqual([1, 2, 2, 1]);
    expect(moved[0]).toBe(items[0]);
    expect(moved[1]).toBe(items[1]);
  });

  it('ignores an unknown item', () => {
    const items = [item(1, 1), item(2, 2)];
    expect(applyMove(items, 9, 1)).toEqual(items);
  });
});

describe('dropIndex', () => {
  const spans = [
    { top: 0, bottom: 40 },
    { top: 40, bottom: 120 },
    { top: 120, bottom: 160 },
  ];

  it('counts the spans whose middle is above the pointer', () => {
    expect(dropIndex(spans, -10)).toBe(0);
    expect(dropIndex(spans, 19)).toBe(0);
    expect(dropIndex(spans, 21)).toBe(1);
    expect(dropIndex(spans, 79)).toBe(1);
    expect(dropIndex(spans, 81)).toBe(2);
    expect(dropIndex(spans, 500)).toBe(3);
  });
});
