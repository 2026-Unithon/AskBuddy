// 화면 글 검사: 중간점(·)을 쓰지 않는다(화면 개선 결정 G4). 주석과 서버 데이터는 대상이 아니다.
// 실행: node scripts/check-copy.mjs  (app, components, lib 아래 .ts·.tsx, app/dev 제외)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const MIDDOT = "·";
const TEXT_KINDS = new Set([
  ts.SyntaxKind.StringLiteral,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral,
  ts.SyntaxKind.TemplateHead,
  ts.SyntaxKind.TemplateMiddle,
  ts.SyntaxKind.TemplateTail,
  ts.SyntaxKind.JsxText,
]);

/** 문자열 리터럴·템플릿·JSX 글 가운데 중간점이 든 것의 줄과 글. */
export function findMiddots(source, fileName) {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const found = [];
  const visit = (node) => {
    if (TEXT_KINDS.has(node.kind)) {
      const text = node.getText(file);
      if (text.includes(MIDDOT)) {
        const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
        found.push({ line: line + 1, text: text.trim() });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

function walk(dir, out) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(name) && !name.endsWith(".d.ts")) out.push(path);
  }
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = join(fileURLToPath(import.meta.url), "..", "..");
  const files = ["app", "components", "lib"].flatMap((dir) => walk(join(root, dir), [])).filter((path) => !relative(root, path).startsWith(join("app", "dev")));
  const problems = files.flatMap((path) => findMiddots(readFileSync(path, "utf8"), path).map((f) => `${relative(root, path)}:${f.line}: ${f.text}`));
  if (problems.length) {
    console.error(`화면 글에 중간점(·)이 ${problems.length}곳 있어요. 개수는 CountBadge, 나열은 쉼표, 메타는 간격으로 나눠 주세요.`);
    for (const line of problems) console.error(line);
    process.exit(1);
  }
}
