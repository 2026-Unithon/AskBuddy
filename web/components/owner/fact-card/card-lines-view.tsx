"use client";

import { Fragment, type ReactNode } from "react";
import { Surface } from "@/components/kit";
import { headingShown, lineLayout } from "@/lib/line-layout";

/** 보기에 필요한 칸만. 사장님 상세(CardFactsView 블록)와 직원 레시피(fact_blocks)가 같은 모양을 넘긴다. */
export type LinesBlock = { key: string; kind: string; heading: string | null; lines: { line_no: number; text: string; pick?: boolean; price?: string | null }[] };

/** 아직 고르지 않은 충돌 값을 인용한 줄 자리(값을 보이지 않는다, 계획 7 Task 6) */
export const PICK_TEXT = "골라 주세요";

// 숫자와 바로 붙은 낱말(2샷, 1000ml, 3,900원)만 굵게. 단위 표 없이 모양으로만 찾는다
const AMOUNT = /\d[\d.,/~]*\s?[A-Za-z가-힣%]*/g;
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

/** 제목 오른쪽 금액(2026-11-18). 규격마다 다르면 한 줄에 하나씩 오른쪽 끝에 붙여 쌓는다. 사장님·직원 같은 부품 */
export function PriceTag({ price }: { price: string[] }) {
  if (price.length === 0) return null;
  return (
    <p data-price="" className="flex shrink-0 flex-col items-end text-[17px] font-bold leading-[1.4] text-ink">
      {price.map((p) => (
        <span key={p} className="whitespace-nowrap">
          {p}
        </span>
      ))}
    </p>
  );
}

/**
 * 카드 보기(계획 10). 사장님 상세·직원 레시피 어디서나 같은 모양이다.
 * 구역 제목은 모델(또는 사장님)이 쓴 것 그대로, 순서 구역은 짧으면 화살표 한 줄·길면 번호 목록, 나머지는 목록.
 */
export function CardLinesView({ blocks }: { blocks: LinesBlock[] }) {
  return (
    <div className="flex flex-col gap-3" data-card-lines="">
      {blocks.map((block, index) => {
        const texts = block.lines.map((line) => line.text);
        const layout = lineLayout(texts, block.kind);
        return (
          <section key={block.key} className="flex flex-col gap-1.5">
            {headingShown(blocks, index) && <h3 className="px-1 text-[17px] font-bold leading-[1.4] tracking-[-0.34px] text-ink [word-break:keep-all]">{block.heading}</h3>}
            <Surface className="px-[18px] py-3.5">
              {layout === "ARROW" ? (
                <ol data-layout="ARROW" className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-[15px] leading-[1.45] text-ink">
                  {block.lines.map((line, i) => (
                    <Fragment key={line.line_no}>
                      {i > 0 && (
                        <li aria-hidden className="text-primary">
                          →
                        </li>
                      )}
                      <li data-line="" className={`max-w-full [word-break:keep-all] ${line.pick ? "font-bold text-warn-700" : ""}`}>
                        {line.pick ? line.text : withAmounts(line.text)}
                      </li>
                    </Fragment>
                  ))}
                </ol>
              ) : layout === "NUMBERED" ? (
                <ol data-layout="NUMBERED" className="flex flex-col gap-2 text-[15px] leading-[1.5] text-ink">
                  {block.lines.map((line, i) => (
                    <li key={line.line_no} data-line="" className="flex gap-2 [word-break:keep-all]">
                      <span aria-hidden className="w-5 shrink-0 font-bold text-primary">
                        {i + 1}
                      </span>
                      <span className={`min-w-0 ${line.pick ? "font-bold text-warn-700" : ""}`}>{line.pick ? line.text : withAmounts(line.text)}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <ul data-layout="LIST" className="flex flex-col gap-2 text-[15px] leading-[1.5] text-ink">
                  {block.lines.map((line) => (
                    <li key={line.line_no} data-line="" className={`[word-break:keep-all] ${line.pick ? "font-bold text-warn-700" : ""}`}>
                      {line.pick ? line.text : withAmounts(line.text)}
                    </li>
                  ))}
                </ul>
              )}
            </Surface>
          </section>
        );
      })}
    </div>
  );
}
