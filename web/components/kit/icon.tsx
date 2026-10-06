import type { CSSProperties } from "react";

// Figma 4-1 페이지에서 내려받은 아이콘(public/figma/icon-*.svg).
// 원본 SVG는 색이 박혀 있어서 mask 로 모양만 쓰고 색은 currentColor 를 따른다.
export type IconName =
  | "camera"
  | "check"
  | "checks"
  | "clip"
  | "clock"
  | "coffee"
  | "home"
  | "layers"
  | "left"
  | "mic"
  | "right"
  | "search"
  | "up";

export function Icon({
  name,
  size = 16,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  const url = `url(/figma/icon-${name}.svg)`;
  const style: CSSProperties = {
    width: size,
    height: size,
    maskImage: url,
    WebkitMaskImage: url,
    maskSize: "contain",
    WebkitMaskSize: "contain",
    maskRepeat: "no-repeat",
    WebkitMaskRepeat: "no-repeat",
    maskPosition: "center",
    WebkitMaskPosition: "center",
  };
  return <span aria-hidden className={`inline-block shrink-0 bg-current ${className}`} style={style} />;
}
