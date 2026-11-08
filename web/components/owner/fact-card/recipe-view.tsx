"use client";

import { Fragment, type ReactNode } from "react";
import { Surface } from "@/components/kit";
import type { CompactRecipe } from "./fact-group";

// 양(숫자+양 단위)만 굵게. 직원이 만들 때 눈으로 찾는 건 넣는 양이다(온도·번호는 굵게 하지 않는다)
const AMOUNT = /\d[\d.,]*\s*(?:ml|mL|g|kg|oz|온즈|펌프|샷|스쿱|개)/g;
function withAmounts(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(AMOUNT)) {
    const at = match.index ?? 0;
    parts.push(text.slice(cursor, at), <strong key={at} className="font-bold">{match[0]}</strong>);
    cursor = at + match[0].length;
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

/**
 * 레시피 한눈에 보기. 규격(HOT/ICE)마다 따로 위아래로, 카드 하나에 만드는 순서 한 줄(컵 → 원액 75ml → 우유가득).
 * 단계는 통째로만 다음 줄로 넘어가고, 단계 이름과 같은 칸의 숫자(컵 16)는 그 단계 바로 아래 작게 붙는다.
 */
export function RecipeView({ recipe }: { recipe: CompactRecipe }) {
  return (
    <div className="flex flex-col gap-3" data-recipe-view="">
      {recipe.sections.map((section, i) => (
        <section key={section.heading ?? i} className="flex flex-col gap-1.5">
          {section.heading && <h3 className="px-1 text-[15px] font-bold leading-[1.4] text-ink">{section.heading}</h3>}
          <Surface className="flex flex-col gap-2 px-4 py-3.5">
            {section.steps.length > 0 && (
              // 아래 붙는 글씨(컵 20온즈)는 칸 폭을 바꾸지 않게 겹쳐 놓고, 그 높이만큼 줄 사이와 아래를 띄운다
              <ol
                className={`flex flex-wrap items-start gap-x-1.5 text-[14px] leading-[1.45] text-ink ${
                  section.steps.some((step) => step.note) ? "gap-y-6 pb-4" : "gap-y-2"
                }`}
              >
                {section.steps.map((step, j) => (
                  <Fragment key={j}>
                    {j > 0 && (
                      <li aria-hidden className="text-primary">
                        →
                      </li>
                    )}
                    <li className="relative max-w-full [word-break:keep-all]">
                      {withAmounts(step.text)}
                      {step.note && (
                        <span className="absolute left-0 top-full whitespace-nowrap text-[12px] leading-[1.3] text-ink-muted">{step.note}</span>
                      )}
                    </li>
                  </Fragment>
                ))}
              </ol>
            )}
            {section.extras.length > 0 && (
              <p className="text-[12px] leading-[1.4] text-ink-muted [word-break:keep-all]">
                {section.extras.map((extra) => `${extra.label} ${extra.value}`).join(", ")}
              </p>
            )}
          </Surface>
        </section>
      ))}
    </div>
  );
}
