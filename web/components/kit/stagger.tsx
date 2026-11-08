import { Children, isValidElement, type ReactNode } from "react";

/**
 * 자식이 차례로(기본 50ms 간격) 아래에서 떠오른다. prefers-reduced-motion 이면 globals.css 가 끈다.
 * 감싸는 칸의 key 는 자식의 key 다. 줄이 빠져도 남은 줄이 다른 줄 자리를 이어받아 다시 떠오르지 않는다.
 */
export function Stagger({ children, step = 50, className = "" }: { children: ReactNode; step?: number; className?: string }) {
  return (
    <div data-stagger="" className={`contents ${className}`}>
      {Children.toArray(children).map((child, i) => (
        <div key={isValidElement(child) && child.key !== null ? child.key : i} className="animate-[stagger-in_var(--dur-base)_var(--ease-out)_both]" style={{ animationDelay: `${i * step}ms` }}>
          {child}
        </div>
      ))}
    </div>
  );
}
