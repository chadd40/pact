import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

// Modal a11y for an overlay panel: on open, move focus inside and remember the
// trigger; trap Tab/Shift+Tab within the panel; ESC to close (when allowed); on
// close/unmount, restore focus to the element that opened it. WCAG 2.4.3 / 2.1.2.
export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  onClose: () => void,
  opts: { closeOnEsc?: boolean } = {}
) {
  const closeOnEsc = opts.closeOnEsc ?? true;
  const stateRef = useRef({ onClose, closeOnEsc });

  useEffect(() => {
    stateRef.current = { onClose, closeOnEsc };
  }, [onClose, closeOnEsc]);

  useEffect(() => {
    const root = ref.current;
    const trigger = document.activeElement as HTMLElement | null;

    const focusables = () =>
      Array.from(root?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      );

    // Move focus inside on open (first focusable, else the panel itself).
    (focusables()[0] ?? root)?.focus?.();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (stateRef.current.closeOnEsc) stateRef.current.onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) {
        e.preventDefault();
        root?.focus?.();
        return;
      }
      const active = document.activeElement as HTMLElement;
      const idx = items.indexOf(active);
      if (e.shiftKey && idx <= 0) {
        e.preventDefault();
        items[items.length - 1].focus();
      } else if (!e.shiftKey && idx === items.length - 1) {
        e.preventDefault();
        items[0].focus();
      } else if (idx === -1) {
        e.preventDefault();
        items[0].focus();
      }
    };

    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      // Restore focus to the trigger if it's still in the document.
      if (trigger && document.contains(trigger)) trigger.focus?.();
    };
  }, [ref]);
}
