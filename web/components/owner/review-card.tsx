"use client";

import Link from "next/link";
import { useState } from "react";
import { focusRing, Sheet, SwipeRow } from "@/components/kit";
import type { CardListItem } from "@/lib/api";
import { useLongPress } from "@/lib/use-long-press";

const MAX_LINES = 4;

/** 카드 내용을 줄로. 넘치면 앞 4줄과 "외 N줄". */
function lines(content: string) {
  const all = content.split("\n").map((line) => line.trim()).filter(Boolean);
  return { shown: all.slice(0, MAX_LINES), more: Math.max(0, all.length - MAX_LINES) };
}

/**
 * 검수 화면의 카드 한 장(o04b). 칩 없이 제목과 내용 줄만, 완성된 카드처럼.
 * - tone="check": 위에 이유 띠, 안에 '고치기'·'빼기' 버튼(맞는지 확인해 주세요)
 * - tone="good": 버튼 없이 누르면 카드 상세(잘 정리됐어요)
 * 둘 다 왼쪽으로 밀면 빼기, 길게 누르면 고치기·카테고리 옮기기·빼기 시트.
 */
export function ReviewCard({
  card,
  tone,
  reason,
  error,
  categories,
  onExclude,
  onMove,
}: {
  card: CardListItem;
  tone: "check" | "good";
  reason?: string;
  error?: string;
  categories: { category_id: number; name: string }[];
  onExclude: () => void;
  onMove: (categoryId: number) => void;
}) {
  const [sheet, setSheet] = useState<"closed" | "menu" | "move">("closed");
  const longPress = useLongPress(() => setSheet("menu"));
  const { shown, more } = lines(card.content);

  const body = (
    <>
      <p className="text-[17px] font-bold leading-[1.45] tracking-[-0.34px] text-ink [word-break:keep-all]">{card.title}</p>
      <ul className="mt-1.5 flex flex-col gap-1 text-[14px] leading-[1.55] tracking-[-0.14px] text-ink-muted">
        {shown.map((line, i) => (
          <li key={i} className="[word-break:keep-all]">
            {line}
          </li>
        ))}
        {more > 0 && <li className="text-[13px]">외 {more}줄</li>}
      </ul>
    </>
  );

  return (
    <>
      {/* 길게 누르기 대상. 글자 선택과 iOS 링크 미리보기가 같이 뜨지 않게 막는다 */}
      <div data-long-press="" className="select-none [-webkit-touch-callout:none]" {...longPress}>
      <SwipeRow left={{ label: "빼기", tone: "danger", onAction: onExclude }}>
        {tone === "check" ? (
          <div className="overflow-hidden rounded-[20px] bg-surface shadow-card">
            <p className="bg-warn-50 px-[18px] py-2 text-[13px] font-medium leading-[1.45] text-warn-700 [word-break:keep-all]">
              {reason ?? "내용이 확실하지 않아요"}
            </p>
            <div className="px-[18px] pb-4 pt-3">
              {body}
              <div className="mt-3 flex gap-2">
                <Link href={`/owner/cards/${card.card_id}`} className={`flex min-h-10 flex-1 items-center justify-center rounded-[12px] bg-empty text-[14px] font-bold text-primary ${focusRing}`}>
                  고치기
                </Link>
                <button type="button" onClick={onExclude} className={`min-h-10 flex-1 rounded-[12px] border-[1.5px] border-danger-200 bg-surface text-[14px] font-bold text-danger-700 ${focusRing}`}>
                  빼기
                </button>
              </div>
            </div>
          </div>
        ) : (
          <Link href={`/owner/cards/${card.card_id}`} draggable={false} className={`block rounded-[20px] bg-surface px-[18px] py-4 shadow-card ${focusRing}`}>
            {body}
          </Link>
        )}
      </SwipeRow>
      {error && <p className="mt-1.5 px-1 text-[12px] text-danger-700">{error}</p>}
      </div>
      <Sheet open={sheet !== "closed"} onClose={() => setSheet("closed")} title={card.title}>
        {sheet === "menu" ? (
          <div className="flex flex-col gap-2">
            <Link href={`/owner/cards/${card.card_id}`} className={`flex min-h-12 items-center rounded-[14px] bg-empty px-4 text-[15px] font-bold text-primary ${focusRing}`}>
              고치기
            </Link>
            <button type="button" onClick={() => setSheet("move")} className={`min-h-12 rounded-[14px] bg-empty px-4 text-left text-[15px] font-bold text-primary ${focusRing}`}>
              카테고리 옮기기
            </button>
            <button
              type="button"
              onClick={() => {
                setSheet("closed");
                onExclude();
              }}
              className={`min-h-12 rounded-[14px] bg-danger-50 px-4 text-left text-[15px] font-bold text-danger-700 ${focusRing}`}
            >
              빼기
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {categories.map((category) => (
              <button
                key={category.category_id}
                type="button"
                aria-pressed={category.category_id === card.category?.category_id}
                onClick={() => {
                  setSheet("closed");
                  onMove(category.category_id);
                }}
                className={`min-h-12 rounded-[14px] px-4 text-left text-[15px] font-bold ${focusRing} ${
                  category.category_id === card.category?.category_id ? "bg-primary text-white" : "bg-empty text-primary"
                }`}
              >
                {category.name}
              </button>
            ))}
          </div>
        )}
      </Sheet>
    </>
  );
}
