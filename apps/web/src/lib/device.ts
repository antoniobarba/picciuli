/**
 * Whether the main pointer is a finger. Focusing a field there pops up the
 * on-screen keyboard, which hides half of the screen, so fields only get
 * focus when tapped.
 */
export function isTouchScreen(): boolean {
  return window.matchMedia?.('(pointer: coarse)').matches ?? false;
}
