import { Children, cloneElement, isValidElement, type ReactNode } from "react";

// Staggered page-load reveal — "one well-orchestrated reveal per screen" (spec §Motion).
//
// Implemented with declarative CSS keyframes rather than a JS animation controller:
// CSS animations are guaranteed to complete when the document is visible and can never
// leave content stranded at opacity 0 (a JS rAF controller stalls while a tab is
// backgrounded). Each direct <Reveal.Item> gets an incremental stagger delay.

interface ItemProps {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  let i = 0;
  const decorated = Children.map(children, (child) => {
    if (
      isValidElement(child) &&
      (child.type as { __isRevealItem?: boolean })?.__isRevealItem
    ) {
      const delay = 0.05 + i * 0.07;
      i += 1;
      return cloneElement(child as React.ReactElement<ItemProps & { __delay?: number }>, {
        __delay: delay,
      } as Partial<ItemProps & { __delay?: number }>);
    }
    return child;
  });
  return <div className={className}>{decorated}</div>;
}

function Item({
  children,
  className,
  style,
  __delay = 0,
}: ItemProps & { __delay?: number }) {
  return (
    <div
      className={`reveal-up${className ? ` ${className}` : ""}`}
      style={{ ...style, "--d": `${__delay}s` } as React.CSSProperties}
    >
      {children}
    </div>
  );
}
Item.__isRevealItem = true;

Reveal.Item = Item;
