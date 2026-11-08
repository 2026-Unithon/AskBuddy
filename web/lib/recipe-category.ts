// 레시피 카테고리 가르기. 카테고리에 종류(레시피/공지/위치…) 정보가 없어 이름으로 본다(서버 카테고리 종류가 생기면 바꾼다: 백로그).
// 쓰는 곳: 카드 목록 두 칸/한 칸(2026-11-07 스케치), 레시피는 근무조를 묻지 않음(2026-11-08).
// 서버 api/app/checklist/repository.py RECIPE_CATEGORY_PATTERN 과 같은 규칙이다.
const RECIPE_NAME = /레시피|음료|메뉴|제조|제작/;

export function isRecipeCategory(name: string): boolean {
  return RECIPE_NAME.test(name);
}
