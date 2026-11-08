// 카드 종류(레시피/할 일/정보). 카테고리 종류(분류 AI 판단, 사장님이 고칠 수 있음, 계획 7 Task 2)가 정본이고,
// 비어 있는 옛 카테고리만 이름으로 본다. node --test 가 바로 읽도록 값 import 없이 둔다.
// 서버 api/app/checklist/repository.py add_default_link 와 같은 규칙이다.
export type CardKind = "RECIPE" | "TASK" | "INFO";

const RECIPE_NAME = /레시피|음료|메뉴|제조|제작/;

export function cardKind(category: { name: string; kind?: CardKind | null } | null | undefined): CardKind {
  if (category?.kind) return category.kind;
  return category && RECIPE_NAME.test(category.name) ? "RECIPE" : "TASK";
}

export const KIND_LABEL: Record<CardKind, string> = { RECIPE: "레시피", TASK: "할 일", INFO: "정보" };
