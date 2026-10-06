import Image from "next/image";

// Figma Buddy (512×512 투명 PNG). unoptimized: 최적화 파이프라인이 알파를 흰 배경으로 누르는 경우가 있다.
export function BuddyImage({ size = 64, className = "" }: { size?: number; className?: string }) {
  return (
    <Image
      src="/figma/buddy.png"
      alt=""
      width={size}
      height={size}
      unoptimized
      loading="eager"
      draggable={false}
      className={`pointer-events-none shrink-0 select-none object-contain ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
