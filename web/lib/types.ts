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
  // 화면 라벨은 "기타"로 보이지만 내부 전송값은 백엔드 enum(SALON)을 그대로 쓴다.
  { key: "SALON", label: "기타", emoji: "🌴" },
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
  { type: "VIDEO", label: "영상", icon: "🎥", weight: 35, formats: "mp4, mov", requiresOther: true },
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
};

export type KnowledgeItem = {
  id: string;
  text: string;
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

export type RoadmapNodeItem = {
  id: string;
  text: string;
  done: boolean;
};

export type RoadmapNode = {
  id: string;
  order: number;
  label: string;
  emoji: string;
  introMessage: string;
  status: NodeStatus;
  items: RoadmapNodeItem[];
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
