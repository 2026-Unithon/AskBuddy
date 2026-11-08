// 낱말 단위 비교(o08a). 제안 화면이 바뀐 부분만 강조하려고 쓴다. node --test 가 바로 읽도록 import 없이 둔다.

export type DiffPart = { text: string; kind: "same" | "del" | "add" };

/**
 * 낱말 LCS. 공백은 비교하지 않는다(공백까지 같은 것으로 잡으면 다 바뀐 글에서 지운 것·넣은 것이 번갈아 나온다).
 * 같은 종류가 이어지면 하나로 합치고, 낱말 사이 원래 공백(줄바꿈 포함)을 보존한다.
 */
export function diffWords(before: string, after: string): DiffPart[] {
  type Token = { w: string; sep: string };
  const tokens = (text: string): Token[] => [...text.matchAll(/(\S+)(\s*)/g)].map((m) => ({ w: m[1], sep: m[2] }));
  const a = tokens(before);
  const b = tokens(after);
  // lcs[i][j]: a[i..], b[j..] 의 가장 긴 공통 부분 길이
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i].w === b[j].w ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const parts: (DiffPart & { pending: string })[] = [];
  const push = (token: Token, kind: DiffPart["kind"]) => {
    const last = parts.at(-1);
    if (last && last.kind === kind) {
      last.text += last.pending + token.w;
      last.pending = token.sep;
      return;
    }
    // 같은 글 뒤에 바뀐 글이 오면 같은 글 쪽에 공백을, 바뀐 글 뒤에 같은 글이 오면 같은 글 앞에 공백을 둔다
    if (last?.kind === "same") last.text += last.pending;
    const lead = last && last.kind !== "same" && kind === "same" ? last.pending : "";
    parts.push({ text: lead + token.w, kind, pending: token.sep });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i].w === b[j].w) {
      push(a[i], "same");
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) push(a[i++], "del");
    else push(b[j++], "add");
  }
  while (i < a.length) push(a[i++], "del");
  while (j < b.length) push(b[j++], "add");
  return parts.map(({ text, kind }) => ({ text, kind }));
}
