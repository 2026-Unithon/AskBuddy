"use client";

import { useState } from "react";
import { BackButton, PageHeader, Screen, Stagger } from "@/components/kit";
import { OwnerAddComposer } from "@/components/owner/owner-add-composer";

// 예시 칩: 누르면 입력창이 그 문장으로 채워진다(o02a)
const EXAMPLES = [
  { label: "레시피", text: "바닐라 라떼는 얼음 가득, 시럽 2펌프, 우유 200에 샷 2개" },
  { label: "마감 순서", text: "마감 때는 머신 청소, 원두 소분, 쓰레기 정리 순서로 해요" },
  { label: "공지", text: "이번 주부터 오트밀크 추가는 500원 받아요" },
];

/** O3 아무거나 넣기. 넣으면 작업 화면(O4)으로 넘어간다 — 추출 진행은 서버 작업 상태가 정본이다. */
export function OwnerAddScreen() {
  const [text, setText] = useState("");
  return (
    <Screen footer={<OwnerAddComposer placeholder="여기에 말하거나 붙여넣기" text={text} onTextChange={setText} />}>
      <BackButton parent="/owner" />
      <Stagger>
        <PageHeader
          title="알려주고 싶은 걸 아무거나 넣어주세요"
          description="레시피, 마감할 일, 공지… 찍거나 파일로 넣으면 레시피와 오늘 할 일로 알아서 나눠요"
        />
        <div role="group" aria-label="예시" className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => {
                setText(example.text);
                // 입력창은 화면 아래(footer)에 있다. 채운 뒤 바로 이어 쓸 수 있게 포커스를 옮긴다
                requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="새로 알려줄 것"]')?.focus());
              }}
              className="min-h-11 rounded-full bg-empty px-4 text-[14px] font-medium text-primary transition-transform duration-150 active:scale-[0.97]"
            >
              {example.label}
            </button>
          ))}
        </div>
      </Stagger>
    </Screen>
  );
}
