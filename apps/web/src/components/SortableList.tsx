import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { dropIndex, type Span } from '../lib/reorder';

export interface SortableOptions<T> {
  getId: (item: T) => number;
  /** The items it can be reordered among, in display order, itself included. */
  siblingsOf: (item: T) => readonly T[];
  /** The rows it occupies on screen, such as a category and its children. */
  extentOf?: (item: T) => readonly T[];
  label: (item: T) => string;
  /** Move the item to a 0-based index among its siblings. */
  onMove: (item: T, index: number) => void;
}

interface Drag<T> {
  id: number;
  item: T;
  mode: 'pointer' | 'keyboard';
  /** Where the item would go, as a 0-based index among its siblings. */
  index: number;
}

const EDGE = 56;
const SCROLL_STEP = 14;

export type HandleProps = ButtonHTMLAttributes<HTMLButtonElement> & { ref: (el: HTMLElement | null) => void };

/**
 * Reorder table rows by dragging their handle with a mouse, a finger or a pen
 * (Pointer Events: HTML5 drag & drop does not fire on most touch screens), or
 * from the keyboard on the focused handle: `alt+↑ ↓` moves one step, `space`
 * picks the row up, `↑ ↓` choose the place and `space` drops it (`esc` cancels).
 */
export function useSortable<T>({ getId, siblingsOf, extentOf = (item) => [item], label, onMove }: SortableOptions<T>) {
  const rows = useRef(new Map<number, HTMLElement>());
  const handles = useRef(new Map<number, HTMLElement>());
  const dragRef = useRef<Drag<T> | null>(null);
  const refocus = useRef<{ item: T; from: number } | null>(null);
  const [drag, setDragState] = useState<Drag<T> | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const helpId = useId();

  const setDrag = (next: Drag<T> | null) => {
    dragRef.current = next;
    setDragState(next);
  };

  const indexOf = (item: T) => siblingsOf(item).findIndex((s) => getId(s) === getId(item));

  // Moving a focused row in the DOM can drop the focus: give it back to its handle.
  useLayoutEffect(() => {
    const pending = refocus.current;
    if (pending === null || indexOf(pending.item) === pending.from) return;
    refocus.current = null;
    const active = document.activeElement;
    if (active && active !== document.body) return;
    handles.current.get(getId(pending.item))?.focus();
  });

  const commit = (item: T, index: number, fromKeyboard: boolean) => {
    const siblings = siblingsOf(item);
    const target = Math.min(Math.max(index, 0), siblings.length - 1);
    if (target === indexOf(item)) return false;
    refocus.current = fromKeyboard ? { item, from: indexOf(item) } : null;
    onMove(item, target);
    setAnnouncement(`${label(item)} moved to position ${target + 1} of ${siblings.length}.`);
    return true;
  };

  // The ids of the first and last rows an item occupies.
  const ends = (item: T): [number, number] => {
    const extent = extentOf(item);
    const first = extent[0] ?? item;
    return [getId(first), getId(extent[extent.length - 1] ?? first)];
  };

  const spans = (item: T): Span[] =>
    siblingsOf(item)
      .filter((s) => getId(s) !== getId(item))
      .flatMap((s) => {
        const [top, bottom] = ends(s);
        const first = rows.current.get(top);
        const last = rows.current.get(bottom);
        return first && last ? [{ top: first.getBoundingClientRect().top, bottom: last.getBoundingClientRect().bottom }] : [];
      });

  const handleProps = (item: T): HandleProps => {
    const id = getId(item);
    const grabbed = drag?.id === id && drag.mode === 'keyboard';
    return {
      ref: (el) => {
        if (el) handles.current.set(id, el);
        else handles.current.delete(id);
      },
      type: 'button',
      'aria-label': `Reorder ${label(item)}`,
      'aria-describedby': helpId,
      'aria-pressed': grabbed,
      disabled: siblingsOf(item).length < 2,
      onClick: (e) => e.stopPropagation(),
      onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
        if (e.button !== 0 || !e.isPrimary) return;
        e.preventDefault();
        e.stopPropagation();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        setDrag({ id, item, mode: 'pointer', index: indexOf(item) });
      },
      onPointerMove: (e: PointerEvent<HTMLButtonElement>) => {
        const current = dragRef.current;
        if (current?.id !== id || current.mode !== 'pointer') return;
        if (e.clientY < EDGE) window.scrollBy(0, -SCROLL_STEP);
        else if (e.clientY > window.innerHeight - EDGE) window.scrollBy(0, SCROLL_STEP);
        const index = dropIndex(spans(item), e.clientY);
        if (index !== current.index) setDrag({ ...current, index });
      },
      onPointerUp: () => {
        const current = dragRef.current;
        if (current?.id !== id || current.mode !== 'pointer') return;
        setDrag(null);
        commit(item, current.index, false);
      },
      onPointerCancel: () => {
        if (dragRef.current?.mode === 'pointer') setDrag(null);
      },
      onBlur: () => {
        if (dragRef.current?.id === id && dragRef.current.mode === 'keyboard') {
          setDrag(null);
          setAnnouncement(`${label(item)}: reordering cancelled.`);
        }
      },
      onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
        const current = dragRef.current;
        const step = e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : 0;
        const pick = e.key === ' ' || e.key === 'Enter';
        if (current?.id === id && current.mode === 'keyboard') {
          if (step) {
            const index = Math.min(Math.max(current.index + step, 0), siblingsOf(item).length - 1);
            setDrag({ ...current, index });
            setAnnouncement(`Position ${index + 1} of ${siblingsOf(item).length}.`);
          } else if (pick) {
            setDrag(null);
            if (!commit(item, current.index, true)) setAnnouncement(`${label(item)} dropped in its place.`);
          } else if (e.key === 'Escape') {
            setDrag(null);
            setAnnouncement(`${label(item)}: reordering cancelled.`);
          } else {
            return;
          }
        } else if (step && e.altKey) {
          commit(item, indexOf(item) + step, true);
        } else if (pick) {
          setDrag({ id, item, mode: 'keyboard', index: indexOf(item) });
          setAnnouncement(`${label(item)} picked up, position ${indexOf(item) + 1}. Use ↑ ↓, then space to drop.`);
        } else {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
      },
    };
  };

  // Where the drop indicator goes: before or after a row of another sibling.
  let indicator: { id: number; side: 'before' | 'after' } | null = null;
  const dragged = drag?.item;
  if (drag && dragged !== undefined && drag.index !== indexOf(dragged)) {
    const others = siblingsOf(dragged).filter((s) => getId(s) !== drag.id);
    const before = others[drag.index];
    const last = others[others.length - 1];
    if (before !== undefined) indicator = { id: ends(before)[0], side: 'before' };
    else if (last !== undefined) indicator = { id: ends(last)[1], side: 'after' };
  }

  return {
    rowRef: (id: number) => (el: HTMLElement | null) => {
      if (el) rows.current.set(id, el);
      else rows.current.delete(id);
    },
    rowClass: (item: T) => {
      const id = getId(item);
      const classes = [];
      if (dragged !== undefined && extentOf(dragged).some((d) => getId(d) === id)) classes.push('dragging');
      if (indicator?.id === id) classes.push(`drop-${indicator.side}`);
      return classes.join(' ');
    },
    handleProps,
    status: (
      <>
        <span id={helpId} hidden>
          Drag to reorder, or press space to pick up, arrow keys to move and space to drop; alt with arrow keys moves one
          step.
        </span>
        <span className="sr-only" role="status" aria-live="assertive">
          {announcement}
        </span>
      </>
    ),
  };
}

export function DragHandle(props: HandleProps) {
  return (
    <button {...props} className="icon-button drag-handle" title="Drag to reorder (space or alt+↑ ↓ from the keyboard)">
      <span aria-hidden="true">⠿</span>
    </button>
  );
}
