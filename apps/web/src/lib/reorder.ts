export interface Positioned {
  id: number;
  /** 1-based display position among the item's siblings. */
  position: number;
}

/**
 * Move an item to a 1-based position among its siblings (the items for which
 * `sameGroup` holds), renumbering them 1…n as the server does. Other items are
 * returned unchanged.
 */
export function applyMove<T extends Positioned>(
  items: readonly T[],
  id: number,
  position: number,
  sameGroup: (a: T, b: T) => boolean = () => true,
): T[] {
  const moved = items.find((item) => item.id === id);
  if (!moved) return [...items];
  const siblings = items
    .filter((item) => sameGroup(item, moved))
    .sort((a, b) => a.position - b.position || a.id - b.id)
    .filter((item) => item.id !== id);
  const index = Math.min(Math.max(position, 1), siblings.length + 1) - 1;
  siblings.splice(index, 0, moved);
  const positions = new Map(siblings.map((item, i) => [item.id, i + 1]));
  return items.map((item) => {
    const next = positions.get(item.id);
    return next === undefined || next === item.position ? item : { ...item, position: next };
  });
}

export interface Span {
  top: number;
  bottom: number;
}

/**
 * Where an item dropped at `y` goes among the other siblings' spans (in display
 * order, the dragged item excluded): the 0-based index of its new position.
 */
export function dropIndex(spans: readonly Span[], y: number): number {
  return spans.filter((span) => (span.top + span.bottom) / 2 < y).length;
}
