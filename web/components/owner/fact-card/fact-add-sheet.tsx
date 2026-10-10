"use client";

// 추가 시트: 점주가 쓴 글 → 서버 분석(제안만, 저장 없음) → 점주가 고르고 고친 제안만 카드 초안에 넣는다.
// 실제 저장은 하단 "고친 내용 저장" 에서 서버가 처음부터 다시 검증한다.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Caption, ErrorInline, Sheet, Surface, focusRing } from "@/components/kit";
import { parseCardFacts, type FactParseResponse, type ParsedFactProposal } from "@/lib/api";
import { useApp } from "@/lib/store";
import { FactFieldsEditor } from "./fact-edit-sheet";
import { blocksProposal, parseErrorMessage, warningText } from "./fact-messages";

const MAX_CHARS = 1000;

type Choice = { proposal: ParsedFactProposal; checked: boolean };

export function FactAddSheet({
  cardId,
  onAdd,
  onClose,
}: {
  cardId: number;
  onAdd: (proposals: ParsedFactProposal[]) => void;
  onClose: () => void;
}) {
  const { state } = useApp();
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ warnings: string[]; choices: Choice[] } | null>(null);
  const parse = useMutation({
    mutationFn: (input: string) => parseCardFacts(cardId, { text: input, mode: "ADD", base_fact_revision_id: null }, state.token!),
    onSuccess: (response: FactParseResponse) =>
      setResult({
        warnings: response.warnings,
        // 다른 대상 같아 보이는 제안은 점주가 직접 골라야 들어간다(조용히 합치지 않음)
        choices: response.proposals.map((proposal) => ({
          proposal,
          checked: !blocksProposal(proposal.warnings) && !proposal.warnings.includes("SUBJECT_MISMATCH"),
        })),
      }),
  });
  const chosen = result?.choices.filter((c) => c.checked && !blocksProposal(c.proposal.warnings)) ?? [];
  const update = (i: number, patch: Partial<Choice>) =>
    setResult((prev) => (prev ? { ...prev, choices: prev.choices.map((c, j) => (j === i ? { ...c, ...patch } : c)) } : prev));

  return (
    <Sheet open onClose={onClose} title="사실 추가" description="한 줄에 하나씩 쓰면 잘 나뉘어요. 분석 결과를 확인한 뒤 카드에 넣어요.">
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium text-ink-muted">넣을 내용</span>
        <textarea
          value={text}
          maxLength={MAX_CHARS}
          rows={4}
          disabled={parse.isPending}
          onChange={(event) => setText(event.target.value)}
          className={`rounded-[16px] bg-surface p-4 text-[16px] leading-[1.6] text-ink shadow-card disabled:opacity-60 ${focusRing}`}
        />
      </label>
      <Caption className="self-end">
        {text.length} / {MAX_CHARS}
      </Caption>
      <Button variant={result ? "secondary" : "primary"} loading={parse.isPending} disabled={!text.trim()} onClick={() => parse.mutate(text)}>
        {parse.isPending ? "분석하는 중" : result ? "다시 분석하기" : "분석하기"}
      </Button>
      {parse.error && <ErrorInline message={parseErrorMessage(parse.error)} onRetry={() => parse.mutate(text)} retrying={parse.isPending} />}
      {result && (
        <div className="flex flex-col gap-3" data-testid="parse-proposals">
          {result.warnings.map((code) => (
            <p key={code} className="rounded-[14px] bg-warn-50 px-3.5 py-2.5 text-[13px] leading-[1.45] text-warn-700 [word-break:keep-all]">
              {warningText(code, result.choices.length)}
            </p>
          ))}
          {result.choices.map((choice, i) => {
            const blocked = blocksProposal(choice.proposal.warnings);
            return (
              <Surface key={choice.proposal.client_ref} className="flex flex-col gap-2 px-4 py-3">
                <label className="flex min-h-11 items-center gap-2 text-[15px] font-bold text-ink">
                  <input
                    type="checkbox"
                    className="size-5 accent-primary"
                    checked={choice.checked && !blocked}
                    disabled={blocked}
                    onChange={(event) => update(i, { checked: event.target.checked })}
                  />
                  제안 {i + 1} {blocked ? "· 넣을 수 없어요" : ""}
                </label>
                {choice.proposal.warnings.map((code) => (
                  <p key={code} className="text-[13px] leading-[1.45] text-warn-700 [word-break:keep-all]">
                    {warningText(code)}
                  </p>
                ))}
                <FactFieldsEditor
                  fields={choice.proposal.fact}
                  showValue
                  disabled={blocked}
                  onChange={(fact) => update(i, { proposal: { ...choice.proposal, fact } })}
                />
              </Surface>
            );
          })}
        </div>
      )}
      {result && (
        <Button
          disabled={chosen.length === 0 || chosen.some((c) => !c.proposal.fact.sentence.trim())}
          onClick={() => onAdd(chosen.map((c) => c.proposal))}
        >
          카드에 넣기{chosen.length > 0 ? ` · ${chosen.length}` : ""}
        </Button>
      )}
      <Button variant="secondary" onClick={onClose}>
        그만두기
      </Button>
    </Sheet>
  );
}
