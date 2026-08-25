import type {
  ChatMessage,
  EmptyKnowledgeAlert,
  KnowledgeSection,
  PendingQuestion,
  RoadmapNode,
  StaffMember,
  TaskCategory,
} from "./types";

// db/002_seed_demo.sql 기준 — 백엔드 미연결 시 화면을 채우는 대체 데이터.
// 실제 배포에서는 lib/api.ts 가 API 호출에 성공하는 즉시 이 값 대신 서버 응답을 쓴다.

export const MOCK_INVITE_CODE = "CAFE-DEMO";
export const MOCK_STORE_NAME = "데모 카페";

export const MOCK_TASK_CATEGORIES: TaskCategory[] = [
  { key: "open", label: "오픈 업무", icon: "🌅", enabled: true },
  { key: "drinks", label: "음료 제조", icon: "🥤", enabled: true },
  { key: "stock", label: "재고 관리", icon: "📦", enabled: true },
  { key: "closing", label: "마감 업무", icon: "🌙", enabled: true },
  { key: "baking", label: "베이킹", icon: "🥐", enabled: false },
];

export const MOCK_KNOWLEDGE_SECTIONS: KnowledgeSection[] = [
  {
    id: "sec-1",
    categoryKey: "stock",
    label: "재고 관리",
    icon: "📦",
    confidence: 87,
    items: [{ id: "item-1", text: "우유는 냉장고 2단 왼쪽 칸. 오픈 전 유통기한 확인." }],
  },
  {
    id: "sec-2",
    categoryKey: "open",
    label: "오픈 업무",
    icon: "🌅",
    confidence: 91,
    items: [{ id: "item-2", text: "오전 7시 오픈 기준 15분 전 도착, 조명·환기 먼저." }],
  },
  {
    id: "sec-3",
    categoryKey: "drinks",
    label: "음료 제조",
    icon: "🥤",
    confidence: 42,
    items: [{ id: "item-3", text: "시럽 재고 부족 시 처리 — 자료에서 명확히 확인되지 않음." }],
  },
];

export const MOCK_ROADMAP: RoadmapNode[] = [
  {
    id: "node-1",
    order: 1,
    label: "오픈 준비",
    emoji: "🌅",
    introMessage: "먼저 오픈 준비부터 같이 볼까요?",
    status: "DONE",
    items: [
      { id: "n1-1", text: "출근 후 조명·환기 순서대로 켜기", done: true },
      { id: "n1-2", text: "포스기·카드단말기 부팅 확인", done: true },
      { id: "n1-3", text: "오늘의 원두·시럽 재고 확인", done: true },
      { id: "n1-4", text: "테이블·의자 정리", done: true },
    ],
  },
  {
    id: "node-2",
    order: 2,
    label: "음료 제조법",
    emoji: "🥤",
    introMessage: "이제 기본 음료 레시피를 익혀봐요.",
    status: "IN_PROGRESS",
    items: [
      { id: "n2-1", text: "아메리카노 추출 비율", done: true },
      { id: "n2-2", text: "라떼 스티밍 온도", done: true },
      { id: "n2-3", text: "시럽 펌프 기본 샷 수", done: false },
      { id: "n2-4", text: "디카페인 원두 구분", done: false },
      { id: "n2-5", text: "테이크아웃 포장 순서", done: false },
    ],
  },
  {
    id: "node-3",
    order: 3,
    label: "재고 관리",
    emoji: "📦",
    introMessage: "재고가 떨어졌을 때 어떻게 해야 하는지 알아봐요.",
    status: "LOCKED",
    items: [
      { id: "n3-1", text: "우유·시럽 보관 위치", done: false },
      { id: "n3-2", text: "재고 부족 시 발주 요청 방법", done: false },
      { id: "n3-3", text: "유통기한 체크 주기", done: false },
    ],
  },
  {
    id: "node-4",
    order: 4,
    label: "마감 업무",
    emoji: "🌙",
    introMessage: "마지막으로 마감 체크리스트예요.",
    status: "LOCKED",
    items: [
      { id: "n4-1", text: "매출 정산 방법", done: false },
      { id: "n4-2", text: "머신 세척 순서", done: false },
      { id: "n4-3", text: "쓰레기 분리배출", done: false },
      { id: "n4-4", text: "보안 시스템 작동", done: false },
    ],
  },
];

export const MOCK_CHAT_HISTORY: ChatMessage[] = [
  {
    id: "msg-1",
    from: "BUDDY",
    text: "안녕하세요! 저는 Buddy예요. 업무 중 궁금한 게 있으면 언제든 물어보세요 🙂",
    createdAt: new Date().toISOString(),
  },
];

export const MOCK_STAFF: StaffMember[] = [
  { id: "staff-1", name: "김민지", label: "알바생 (3일차)", progressPct: 82, level: "great" },
  { id: "staff-2", name: "박서준", label: "알바생 (1일차)", progressPct: 35, level: "warn" },
];

export const MOCK_PENDING_QUESTIONS: PendingQuestion[] = [
  {
    id: "pq-1",
    askedBy: "박서준",
    questionText: "시럽 재고 부족하면 어떻게 하나요?",
    createdAt: new Date().toISOString(),
  },
];

export const MOCK_EMPTY_KNOWLEDGE: EmptyKnowledgeAlert[] = [
  { id: "gap-1", topic: "발주 처리 방법" },
];
