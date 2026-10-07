/** 카드 본문 줄을 Figma O10·A8 처럼 번호 목록으로 보여준다. 한 줄이면 번호를 달지 않는다. */
export function NumberedContent({ content }: { content: string }) {
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length <= 1) {
    return <p className="whitespace-pre-wrap text-[16px] leading-[1.6] tracking-[-0.16px] text-ink">{content}</p>;
  }
  return (
    <ol className="flex flex-col gap-1">
      {lines.map((line, index) => (
        <li key={index} className="flex gap-2 text-[16px] leading-[1.6] tracking-[-0.16px] text-ink">
          <span className="w-4 shrink-0 text-ink-muted">{index + 1}</span>
          <span className="min-w-0 flex-1 [word-break:keep-all]">{line}</span>
        </li>
      ))}
    </ol>
  );
}
