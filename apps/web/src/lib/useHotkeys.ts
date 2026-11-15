import { useEffect, useRef } from 'react';

export type Hotkeys = Record<string, (event: KeyboardEvent) => void>;

/** `ctrl+k`, `shift+ArrowUp`, `?`, `n`… from a keyboard event. */
export function keyName(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push('ctrl');
  if (event.altKey) parts.push('alt');
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  // Shift is implied by printable characters such as `?` or `]`.
  if (event.shiftKey && event.key.length > 1) parts.push('shift');
  parts.push(key);
  return parts.join('+');
}

function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

function dialogOpen(): boolean {
  return document.querySelector('[role="dialog"], [role="menu"]') !== null;
}

/**
 * Global keyboard shortcuts, as in the console interface. They are ignored
 * while typing in a field or while a dialog is open, except `ctrl+…` keys.
 */
export function useHotkeys(bindings: Hotkeys, enabled = true): void {
  const current = useRef(bindings);
  useEffect(() => {
    current.current = bindings;
  });
  useEffect(() => {
    if (!enabled) return;
    const handler = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      const name = keyName(event);
      const action = current.current[name];
      if (!action) return;
      const withModifier = name.startsWith('ctrl+');
      if (!withModifier && (typing(event.target) || dialogOpen())) return;
      event.preventDefault();
      action(event);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [enabled]);
}
