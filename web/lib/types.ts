export type Role = "OWNER" | "STAFF";

export type BusinessType =
  | "CAFE"
  | "RESTAURANT"
  | "BAKERY"
  | "BAR"
  | "CVS"
  | "SALON";

export const BUSINESS_TYPES: { key: BusinessType; label: string; emoji: string }[] = [
  { key: "CAFE", label: "카페", emoji: "☕" },
  { key: "RESTAURANT", label: "식당", emoji: "🍽️" },
  { key: "BAKERY", label: "베이커리", emoji: "🥐" },
  { key: "BAR", label: "바·주점", emoji: "🍺" },
  { key: "CVS", label: "편의점", emoji: "🏪" },
  { key: "SALON", label: "미용실", emoji: "💇" },
];

export type TaskCategory = {
  key: string;
  label: string;
  icon: string;
  enabled: boolean;
};

export type UploadSourceType = "VOICE" | "VIDEO" | "KAKAO" | "SCAN";

export const UPLOAD_METHODS: {
  type: UploadSourceType;
  label: string;
  icon: string;
  weight: number;
  formats: string;
  requiresOther?: boolean;
}[] = [
  { type: "VOICE", label: "음성", icon: "🎙️", weight: 25, formats: "mp3, m4a, wav" },
  { type: "VIDEO", label: "영상", icon: "🎥", weight: 35, formats: "mp4, mov" },
  { type: "KAKAO", label: "카카오톡 대화", icon: "💬", weight: 25, formats: "txt" },
  { type: "SCAN", label: "파일 스캔", icon: "📄", weight: 15, formats: "pdf, jpg, png" },
];

export type SourceStatus = "UPLOADED" | "PROCESSING" | "DONE" | "FAILED";

export type UploadSource = {
  id: string;
  type: UploadSourceType;
  title: string;
  status: SourceStatus;
  errorMessage?: string;
  // 백엔드가 매긴 sources.source_id. 미리보기가 "이번에 올린 것" 만 뽑을 때 쓴다.
  sourceId?: number;
};

export type KnowledgeItem = {
  id: string;
  text: string;
  /** 카드 본문. 제목만으론 무슨 내용인지 알 수 없어 함께 보여준다. */
  detail?: string;
};

export type KnowledgeSection = {
  id: string;
  categoryKey: string;
  label: string;
  icon: string;
  confidence: number; // 0~100
  items: KnowledgeItem[];
};

export type NodeStatus = "DONE" | "IN_PROGRESS" | "LOCKED";

export type DetailCard =
  | { type: "doc"; title: string; image?: string; text: string; tags?: string[] }
  | { type: "buddy"; text: string };

export type RoadmapNode = {
  id: string;
  order: number;
  label: string;
  emoji: string;
  introMessage: string;
  status: NodeStatus;
  /** 경로 배경 이미지(616×1089) 기준 원본 좌표 — % 환산해 반응형으로 배치한다 */
  pos: { x: number; y: number };
  details: DetailCard[];
};

export type ChatFrom = "BUDDY" | "USER";

export type Citation = {
  cardId: string;
  title: string;
};

export type ChatMessage = {
  id: string;
  from: ChatFrom;
  text: string;
  pending?: boolean;
  citations?: Citation[];
  createdAt: string;
};

export type StaffLevel = "great" | "good" | "warn";

export type StaffMember = {
  id: string;
  name: string;
  label: string;
  progressPct: number;
  level: StaffLevel;
};

export type PendingQuestion = {
  id: string;
  askedBy: string;
  questionText: string;
  createdAt: string;
};

export type EmptyKnowledgeAlert = {
  id: string;
  topic: string;
};

export type StoreProfile = {
  slug: string;
  name: string;
  businessType: BusinessType | null;
  inviteCode: string;
};
