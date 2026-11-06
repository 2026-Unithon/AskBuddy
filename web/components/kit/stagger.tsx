import { Children, type ReactNode } from "react";

/** 자식이 차례로(기본 50ms 간격) 아래에서 떠오른다. prefers-reduced-motion 이면 globals.css 가 끈다. */
export function Stagger({ children, step = 50, className = "" }: { children: ReactNode; step?: number; className?: string }) {
  return (
    <div data-stagger="" className={`contents ${className}`}>
      {Children.toArray(children).map((child, i) => (
        <div key={i} className="animate-[stagger-in_var(--dur-base)_var(--ease-out)_both]" style={{ animationDelay: `${i * step}ms` }}>
          {child}
        </div>
      ))}
    </div>
  );
}
