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
    id: "sec-3",
    categoryKey: "drinks",
    label: "음료 제작",
    icon: "🧋",
    confidence: 42,
    items: [
      { id: "item-3a", text: "시럽 재고 부족 시 처리 — 자료에서 명확히 확인되지 않음" },
      { id: "item-3b", text: "계절 메뉴 3종 레시피 등록됨" },
    ],
  },
  {
    id: "sec-1",
    categoryKey: "stock",
    label: "재고 관리",
    icon: "📦",
    confidence: 78,
    items: [
      { id: "item-1a", text: "우유 종류: 일반·저지방·오트" },
      { id: "item-1b", text: "우유는 냉장고 2단 왼쪽 칸. 오픈 전 유통기한 확인" },
      { id: "item-1c", text: "주 2회 발주 (월·목)" },
    ],
  },
  {
    id: "sec-2",
    categoryKey: "open",
    label: "오픈 업무",
    icon: "🌅",
    confidence: 92,
    items: [
      { id: "item-2a", text: "오전 7시 오픈 기준 15분 전 도착" },
      { id: "item-2b", text: "커피머신 예열 (약 10분 소요)" },
      { id: "item-2c", text: "냉장고 재고 확인 및 진열" },
    ],
  },
];

// 경로 화면(roadmap-bg.png, 616×1089). 원 7개는 지그재그 돌 중심(계산값)에 앉힌다.
export const ROADMAP_BG_SIZE = { width: 616, height: 1089 };

export const MOCK_ROADMAP: RoadmapNode[] = [
  {
    id: "node-1",
    order: 1,
    label: "매장 둘러보기",
    emoji: "🏪",
    introMessage: "가게 투어 완료! 어디에 뭐가 있는지 이제 알겠죠?",
    status: "DONE",
    pos: { x: 244, y: 1058 }, // 돌 1 시작
    details: [
      {
        type: "doc",
        title: "매장 전체 구조",
        text: "카운터, 주방, 창고, 화장실 위치를 먼저 파악해요.\n\n📍 카운터: 입구 정면\n📍 주방: 카운터 뒤편\n📍 창고: 주방 왼쪽 문 안\n📍 화장실: 홀 오른쪽 끝\n\n비상구는 입구 왼쪽에 있어요. 꼭 기억해두세요!",
      },
      { type: "buddy", text: "매장 구조가 헷갈리면 '매장 지도' 라고 채팅하면 도면을 보내드려요 🦜" },
    ],
  },
  {
    id: "node-2",
    order: 2,
    label: "오픈 준비",
    emoji: "☀️",
    introMessage: "오픈 준비 완료! 손님 맞을 준비가 됐어요.",
    status: "DONE",
    pos: { x: 456, y: 916 }, // 돌 4 우측 꺾임
    details: [
      {
        type: "doc",
        title: "오픈 체크리스트",
        text: "① 조명 전체 켜기 (스위치: 입구 왼쪽 벽)\n\n② 냉장고·냉동고 온도 확인\n   냉장 2–5°C / 냉동 -18°C 이하\n\n③ 커피머신 예열 시작 (15분 소요)\n   머신 왼쪽 상단 전원 버튼\n\n④ 재고 수량 확인 후 부족한 것 메모\n\n⑤ 테이블 정리 및 청소",
      },
      { type: "buddy", text: "오픈 준비 순서가 헷갈리면 '오픈 순서 알려줘' 라고 채팅하면 알려드려요 🦜" },
    ],
  },
  {
    id: "node-3",
    order: 3,
    label: "재고 위치 파악",
    emoji: "📦",
    introMessage: "재고 위치를 완벽히 파악했어요!",
    status: "DONE",
    pos: { x: 409, y: 748 }, // 돌 6 좌상 구간
    details: [
      {
        type: "doc",
        title: "소모품 서랍",
        image: "/images/drawer.png",
        text: "카운터 아래 2단 서랍장이에요.\n\n📍 위치: 계산대 바로 밑, 왼쪽 문 열면 있어요.\n\n• 1칸 왼쪽: 투명 플라스틱 컵 (아이스 음료용)\n• 1칸 오른쪽: 종이컵 묶음 (핫 음료용)\n• 2칸 왼쪽: 흰색 컵 대용량 묶음\n• 2칸 오른쪽: 중간 사이즈 컵 묶음\n\n컵이 부족하면 창고 2번 선반에 보충분 있어요.",
      },
      { type: "buddy", text: "컵 종류가 헷갈리면 저한테 물어봐요! '아이스 컵 어디 있어?' 라고 채팅하면 알려드려요 🦜" },
    ],
  },
  {
    id: "node-4",
    order: 4,
    label: "음료 제조법",
    emoji: "☕",
    introMessage: "음료 제조법 미션 시작! 레시피 순서대로 따라가 봐요 ☕",
    status: "IN_PROGRESS",
    pos: { x: 223, y: 581 }, // 돌 9 좌측 꺾임
    details: [
      {
        type: "doc",
        title: "아이스 아메리카노",
        text: "① 소모품 서랍에서 투명 아이스 컵(대) 꺼내기\n\n② 컵에 얼음을 2/3 정도 채우기\n\n③ 정수기 냉수로 컵의 절반까지 물 채우기\n   (물 먼저 넣어야 에스프레소가 골고루 섞여요)\n\n④ 커피머신 앞에 컵 놓고\n   머신 왼쪽 버튼 2번 누르기 → 더블샷 추출\n   (싱글은 1번, 더블은 2번)\n\n⑤ 샷이 다 나오면 뚜껑+빨대 꽂아서 완성",
        tags: ["#아이스", "#기본메뉴", "#2분소요"],
      },
      {
        type: "doc",
        title: "핫 아메리카노",
        text: "① 종이컵(중) 꺼내기 — 소모품 서랍 1칸 오른쪽\n\n② 뜨거운 물을 컵의 2/3까지 채우기\n   (정수기 온수 버튼 — 빨간색)\n\n③ 커피머신 왼쪽 버튼 1번 누르기 → 싱글샷\n\n④ 뚜껑 닫아서 완성\n   (뚜껑은 카운터 오른쪽 정리함에 있어요)",
        tags: ["#핫", "#기본메뉴", "#1분30초"],
      },
      { type: "buddy", text: "제조 중에 모르는 게 생기면 채팅탭에서 'OOO 만드는 방법' 이라고 물어보면 바로 알려드려요! 🦜" },
    ],
  },
  {
    id: "node-5",
    order: 5,
    label: "마감 루틴",
    emoji: "🌙",
    introMessage: "마감 업무를 배워볼까요?",
    status: "LOCKED",
    pos: { x: 358, y: 401 }, // 돌 12 우상 구간
    details: [
      { type: "doc", title: "마감 체크리스트", text: "① 매출 정산\n② 머신 세척\n③ 쓰레기 분리배출\n④ 보안 시스템 작동 확인" },
      { type: "buddy", text: "마감 순서가 궁금하면 '마감 순서 알려줘' 라고 물어보세요 🦜" },
    ],
  },
  {
    id: "node-6",
    order: 6,
    label: "단골 응대법",
    emoji: "🤝",
    introMessage: "단골 손님 응대법을 배워볼까요?",
    status: "LOCKED",
    pos: { x: 463, y: 291 }, // 돌 14 우측 꺾임
    details: [
      { type: "doc", title: "단골 응대", text: "① 자주 오시는 손님 얼굴·이름 기억하기\n② 즐겨 시키는 메뉴 파악\n③ 먼저 인사하고 안부 묻기" },
      { type: "buddy", text: "단골 손님 정보는 채팅으로 '단골 정보' 라고 물어보면 알려드려요 🦜" },
    ],
  },
  {
    id: "node-7",
    order: 7,
    label: "혼자 오픈하기",
    emoji: "🔑",
    introMessage: "이제 혼자서도 오픈할 수 있어요!",
    status: "LOCKED",
    pos: { x: 270, y: 74 }, // 돌 17 선물
    details: [
      { type: "doc", title: "혼자 오픈하기", text: "① 오픈 체크리스트 순서대로 진행\n② 비상 연락처 확인\n③ 문제 발생 시 사장님께 바로 연락" },
      { type: "buddy", text: "여기까지 왔다면 이제 진짜 베테랑이에요! 축하해요 🎉" },
    ],
  },
];

export const MOCK_CHAT_HISTORY: ChatMessage[] = [
  {
    id: "msg-1",
    from: "BUDDY",
    text: "안녕하세요! 저는 Buddy예요 😊 업무에 대해 궁금한 점이 있으면 편하게 물어보세요!",
    createdAt: new Date().toISOString(),
  },
  {
    id: "msg-2",
    from: "USER",
    text: "냉장고 안에 있는 우유는 어디에 보관해요?",
    createdAt: new Date().toISOString(),
  },
  {
    id: "msg-3",
    from: "BUDDY",
    text: "우유는 냉장고 2단 왼쪽 칸에 보관해요! 유통기한 확인은 매일 오픈 전에 꼭 해주세요 🥛",
    citations: [{ cardId: "sec-1", title: "재고 관리" }],
    createdAt: new Date().toISOString(),
  },
  {
    id: "msg-4",
    from: "USER",
    text: "시럽 재고가 부족하면 어떻게 해야 해요?",
    createdAt: new Date().toISOString(),
  },
  {
    id: "msg-5",
    from: "BUDDY",
    text: "이 질문은 아직 등록된 내용이 없어요. 사장님께 확인 중이에요! 잠시만 기다려주세요 😊",
    pending: true,
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
