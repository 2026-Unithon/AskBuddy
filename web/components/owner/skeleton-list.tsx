"use client";

interface SkeletonListProps {
  count?: number;
  heightClass?: string;
  className?: string;
  label?: string;
}

export function SkeletonList({
  count = 3,
  heightClass = "h-24",
  className = "",
  label = "콘텐츠 불러오는 중",
}: SkeletonListProps) {
  return (
    <div className={`space-y-3 ${className}`} aria-label={label} role="status">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`w-full animate-pulse rounded-2xl bg-surface-muted/60 border border-border/40 ${heightClass}`}
        />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

