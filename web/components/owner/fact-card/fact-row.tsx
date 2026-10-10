"use client";

// 사실 한 줄: 단계 번호·문장·값·부정·조건/예외·선행·근거. 편집 중이면 고치기·빼기·위/아래.
import { Chip, focusRing } from "@/components/kit";
import type { EditBlockKind, FactFields, FactOrigin, FactRow, FactVariant } from "@/lib/api";

const BLOCK_NAME: Record<EditBlockKind | "RAW", string> = { QUANTITIES: "수치", STEPS: "순서", NOTES: "목록", RAW: "내용" };

export function variantLabel(variant: FactVariant): string {
  const parts = [variant.temperature, variant.size].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "규격 표시 없음";
}

export function blockLabel(kind: EditBlockKind | "RAW", variant: FactVariant): string {
  return `${BLOCK_NAME[kind]} · ${variantLabel(variant)}`;
}

function monthDay(iso: string | null): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" }).format(new Date(iso));
}

function locationLabel(origin: FactOrigin): string | null {
  const n = (key: string) => {
    const value = origin.locator[key];
    return typeof value === "number" ? value : null;
  };
  if (origin.locator_type === "PAGE" && n("page")) return `${n("page")}쪽`;
  if (origin.locator_type === "LINE" && n("line")) return `${n("line")}번째 줄`;
  if (origin.locator_type === "TIMESTAMP" && n("timestamp_sec") !== null) {
    const sec = n("timestamp_sec") ?? 0;
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  }
  return null;
}

/** common §8 근거 이름·위치 규칙. */
export function originLabel(origin: FactOrigin): string {
  if (origin.kind === "OWNER_ANSWER") return "사장님 답변";
  if (origin.kind === "OWNER_TEXT") return `사장님 직접 입력 · ${monthDay(origin.created_at)}`;
  const name = origin.source_title ?? "자료";
  const where = locationLabel(origin);
  const broken = origin.source_availability === "DELETED" ? " · 인용 끊김" : "";
  return `${name}${where ? ` · ${where}` : ""}${broken}`;
}

const EDIT_BLOCK_TEXT: Record<NonNullable<FactRow["edit_block"]>, { chip: string; text: string }> = {
  CHANGED_ELSEWHERE: { chip: "다른 곳에서 고쳐짐", text: "이 사실은 다른 곳에서 먼저 고쳐졌어요. 빼고 새로 넣어 주세요." },
  MOVED_ENTITY: { chip: "메뉴 정리 바뀜", text: "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요. 빼고 새로 넣어 주세요." },
};

export type FactRowEdit = {
  locked: boolean;
  isSteps: boolean;
  canUp: boolean;
  canDown: boolean;
  onEdit: () => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
};

function SmallButton({ label, onClick, disabled, children }: { label?: string; onClick: () => void; disabled?: boolean; children: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={`min-h-11 min-w-11 rounded-full bg-background px-3 text-[13px] font-bold text-primary disabled:opacity-40 ${focusRing}`}
    >
      {children}
    </button>
  );
}

export function FactRowItem({
  fields,
  base,
  state,
  flagged = false,
  requireLabels,
  edit,
}: {
  fields: FactFields;
  base: FactRow | null;
  /** 편집 중 표시: 고친 줄 / 새로 넣은 줄 */
  state?: "MODIFIED" | "ADDED" | null;
  flagged?: boolean;
  /** 편집 중: 같은 블록 선행은 지금 초안 번호로 다시 그린 라벨. 없으면 서버 라벨 */
  requireLabels?: string[];
  edit?: FactRowEdit;
}) {
  const blocked = base?.edit_block ? EDIT_BLOCK_TEXT[base.edit_block] : null;
  const shortSentence = fields.sentence.length > 20 ? `${fields.sentence.slice(0, 20)}…` : fields.sentence;
  return (
    <li
      data-testid="fact-row"
      className={`flex flex-col gap-1.5 border-b border-background py-3 last:border-b-0 ${flagged ? "rounded-[12px] bg-danger-50 px-2" : ""}`}
    >
      <div className="flex items-start gap-2">
        {fields.step_order !== null && (
          <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-empty text-[12px] font-bold text-primary">
            {fields.step_order}
          </span>
        )}
        <p className="min-w-0 flex-1 text-[16px] leading-[1.5] text-ink [overflow-wrap:anywhere] [word-break:keep-all]">{fields.sentence}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {fields.value && <Chip size="sm" tone="brand">{`${fields.value}${fields.unit ?? ""}`}</Chip>}
        {fields.polarity === "NEGATE" && <Chip size="sm" tone="danger">하지 않음</Chip>}
        {state === "MODIFIED" && <Chip size="sm" tone="warn">고침</Chip>}
        {state === "ADDED" && <Chip size="sm" tone="warn">새로 넣음</Chip>}
        {blocked && <Chip size="sm" tone="warn">{blocked.chip}</Chip>}
        {flagged && <Chip size="sm" tone="danger">이 줄을 확인해 주세요</Chip>}
      </div>
      {fields.conditions.length > 0 && <p className="text-[13px] leading-[1.45] text-ink-muted">조건 · {fields.conditions.join(" / ")}</p>}
      {fields.exceptions.length > 0 && <p className="text-[13px] leading-[1.45] text-ink-muted">예외 · {fields.exceptions.join(" / ")}</p>}
      {base && base.requires.length > 0 && (
        <p className="text-[13px] leading-[1.45] text-ink-muted">먼저: {(requireLabels ?? base.requires.map((r) => r.label)).join(", ")}</p>
      )}
      {blocked && <p className="text-[13px] leading-[1.45] text-warn-700 [word-break:keep-all]">{blocked.text}</p>}
      {base ? (
        <div className="flex flex-col gap-0.5" data-testid="fact-origins">
          {base.origins.map((origin, i) => (
            <p key={i} className="text-[12px] leading-[1.45] text-ink-muted [overflow-wrap:anywhere]">
              근거 · {originLabel(origin)}
            </p>
          ))}
          {base.previous_sentence && (
            <p className="text-[12px] leading-[1.45] text-ink-muted [overflow-wrap:anywhere]">이전: {base.previous_sentence}</p>
          )}
        </div>
      ) : (
        <p className="text-[12px] leading-[1.45] text-ink-muted">저장하면 근거가 &lsquo;사장님 직접 입력&rsquo;으로 남아요</p>
      )}
      {edit && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <SmallButton label={`고치기 · ${shortSentence}`} onClick={edit.onEdit} disabled={edit.locked || Boolean(blocked)}>
            고치기
          </SmallButton>
          <SmallButton label={`빼기 · ${shortSentence}`} onClick={edit.onRemove} disabled={edit.locked}>
            빼기
          </SmallButton>
          <SmallButton
            label={edit.isSteps ? `위로 · 일하는 순서가 바뀌어요 · ${shortSentence}` : `위로 · ${shortSentence}`}
            onClick={() => edit.onMove(-1)}
            disabled={edit.locked || !edit.canUp}
          >
            위로
          </SmallButton>
          <SmallButton
            label={edit.isSteps ? `아래로 · 일하는 순서가 바뀌어요 · ${shortSentence}` : `아래로 · ${shortSentence}`}
            onClick={() => edit.onMove(1)}
            disabled={edit.locked || !edit.canDown}
          >
            아래로
          </SmallButton>
        </div>
      )}
    </li>
  );
}
