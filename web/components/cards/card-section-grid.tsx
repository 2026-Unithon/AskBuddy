"use client";

import type { HTMLAttributes, ReactNode } from "react";

/**
 * 카드 목록의 구역·격자(계획 10). 사장님 카드 목록과 직원 레시피 목록이 같은 부품을 쓴다.
 * 구역마다 굵은 밑줄 머리, 레시피 구역은 2열 타일, 나머지는 1열.
 */
export function CardSectionGrid<T>({
  items,
  sectionOf,
  kindOf,
  renderTile,
  sectionOrder,
  gridProps,
  idPrefix = "cards-section",
}: {
  items: T[];
  sectionOf: (item: T) => string;
  kindOf: (item: T) => "RECIPE" | "TASK" | "INFO" | null;
  renderTile: (item: T) => ReactNode;
  /** 구역 순서(작을수록 위). 없으면 처음 나온 순서 */
  sectionOrder?: (name: string) => number;
  /** 격자에 붙일 속성(사장님 선택 모드의 끌어 고르기) */
  gridProps?: HTMLAttributes<HTMLDivElement>;
  idPrefix?: string;
}) {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const name = sectionOf(item);
    groups.set(name, [...(groups.get(name) ?? []), item]);
  }
  const sections = [...groups.entries()];
  if (sectionOrder) sections.sort(([a], [b]) => sectionOrder(a) - sectionOrder(b));
  return (
    <>
      {sections.map(([name, list], index) => {
        // aria-labelledby 는 공백으로 id 를 나누므로 이름 대신 순번으로 id 를 만든다
        const id = `${idPrefix}-${index}`;
        return (
          <section key={name} aria-labelledby={id} className="flex flex-col gap-3">
            <h2 id={id} className="border-b-2 border-ink pb-1.5 text-[17px] font-bold leading-[1.4] tracking-[-0.34px] text-ink">
              {name}
            </h2>
            <div className={`grid gap-3 ${kindOf(list[0]) === "RECIPE" ? "grid-cols-2" : "grid-cols-1"}`} {...gridProps}>
              {list.map((item) => renderTile(item))}
            </div>
          </section>
        );
      })}
    </>
  );
}
