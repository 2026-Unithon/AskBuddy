"""공용 — 환경변수 로딩. 수정 전 팀 합의."""
from functools import lru_cache
from typing import Literal
from pydantic import Field, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 신규 v2 API는 DB/의미 인수 후 별도 활성화한다. v1 동작을 암묵 전환하지 않는다.
    r_v2_enabled: bool = False
    r_reranker_enabled: bool = False
    r_reviewed_semantics_enabled: bool = False
    r_reviewed_semantics_path: str = ''
    r_reviewed_semantics_hash: str = ''
    r_general_semantics_enabled: bool = False
    r_general_semantics_path: str = ''
    r_general_semantics_hash: str = ''
    # C0 §6: 조정 가능한 초기값. 프로세스마다 별도 카운터를 두지 않는다.
    chat_deadline_seconds: float = Field(default=5.0, gt=0, le=5)
    search_deadline_seconds: float = Field(default=1.0, gt=0, le=1)
    answer_deadline_seconds: float = Field(default=3.0, gt=0, le=3)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=30)
    query_embedding_timeout_seconds: float = Field(default=0.8, gt=0, le=1)
    llm_total_budget_seconds: float = Field(default=3.0, gt=0, le=3)
    chat_save_reserve_seconds: float = Field(default=0.5, ge=0.5, lt=5)
    request_member_per_minute: int = Field(default=20, ge=1)
    request_store_per_minute: int = Field(default=120, ge=1)
    request_member_concurrency: int = Field(default=2, ge=1)
    request_store_concurrency: int = Field(default=8, ge=1)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "askbuddy"
    env: str = "local"
    allowed_origins: str = "http://localhost:3000"

    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # D3·D4·D11. 코드에서 리터럴로 쓰지 말고 여기를 참조한다
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    confidence_threshold: float = 0.6  # D3 — 카드 검수 우선노출. 검색과 무관
    retrieval_threshold: float = 0.35  # D11 — 검색 게이트 하한. D3와 별개
    # 구버전 호환 설정. 8단계부터는 점수가 높아도 질문 대상어 근거가 없으면 miss다.
    retrieval_strong_score: float = 0.62
    # 직원 답변은 기본적으로 근거 제한 LLM을 사용하되, 호출/검증 실패 시 카드 원문으로 폴백한다.
    answer_mode: Literal["extractive", "grounded_llm"] = "grounded_llm"
    frame_interval_sec: int = 3
    # R이 출처 없는 원문 인용을 처리하기 전까지 점주 답변 출처 카드를 공개하지 않는다
    w_owner_answer_raw_publish: bool = False
    # 점주 답변 반영 worker. 켜면 lifespan 이 주기마다 OWNER_ANSWER_SUBMITTED 사건을 소비한다
    w_owner_answer_worker_enabled: bool = False
    w_owner_answer_worker_interval_sec: int = 10

    # 실제 자료 측정 전에는 null이다. 값이 설정된 제한만 서버가 강제한다.
    ingest_voice_max_bytes: int | None = None
    ingest_voice_max_duration_sec: int | None = None
    ingest_video_max_bytes: int | None = None
    ingest_video_max_duration_sec: int | None = None
    ingest_kakao_max_bytes: int | None = None
    ingest_scan_max_bytes: int | None = None
    ingest_scan_max_pages: int | None = None

    # ingest (준혁) — mock: LLM 미호출(M1 기본값) / real: Gemini 호출
    ingest_mode: Literal["mock", "real"] = "mock"
    gemini_model: str = "gemini-3.6-flash"
    stt_model: str = "whisper-1"

    # 영상 입력 실험 (이관경계_실험설계.md 4절 E4).
    # 기본값은 현재 검증된 경로다. 실험은 플래그로 opt-in 한다.
    #   frames — 프레임을 솎아 이미지로 투입 (현재 기본)
    #   native — 원본 영상을 Gemini Files API 로 통째 투입. 토큰이 10배 이상 늘 수 있다
    video_input_mode: Literal["frames", "native"] = "frames"
    # 모델에 넣을 최대 프레임 수. 0 이면 상한 없음(추출된 전부).
    # 몇 장이 최적인지는 가정하지 말고 하네스로 정한다
    video_max_frames_to_model: int = 20
    # 긴 입력을 몇 초 구간으로 쪼개 map 할지. 0 이면 쪼개지 않는다(현재 검증된 경로).
    # store-a 실측: 38분 영상에서 정답지 62건 중 61건을 '아예 못 뽑았다'(EXTRACTION).
    # 프레임을 20→200 장으로 올려도 개선이 0건이었다 — 볼 게 없어서가 아니라
    # 한 호출에 38분을 담으라는 요구 자체가 무리다
    video_segment_sec: int = 0
    # 이웃 구간과 겹쳐 볼 초. 0 이면 겹치지 않는다(기존 동작). 겹치면 경계 사실이
    # 두 구간에서 함께 뽑힐 수 있다 — 켜기 전에 중복을 하네스로 확인한다 (W1-2)
    video_segment_overlap_sec: int = Field(default=0, ge=0)
    # 구간 추출을 몇 개까지 동시에 부를지. 1 이면 앞 구간부터 차례대로(기존 동작) (W1-2)
    extract_segment_concurrency: int = Field(default=1, ge=1)

    # 출력 token 상한 (W1-2). None 이면 넘기지 않는다 — 공급자 기본값(기존 동작).
    # 측정 전이라 값을 가정하지 않는다. 상한에 닿아 잘린 응답(MAX_TOKENS)은
    # 상한 설정과 무관하게 언제나 성공으로 처리하지 않는다
    extract_max_output_tokens: int | None = Field(default=None, ge=1)
    assemble_max_output_tokens: int | None = Field(default=None, ge=1)
    # 잘린 추출을 반으로 나눠 다시 뽑는 깊이 상한 (W1-2). 0 이면 나누지 않는다(기본, 꺼 둠).
    # 깊이 d 까지 나누면 한 구간이 최대 2^(d+1)-1 번 호출된다 — 비용 상한을 함께 본다
    extract_truncation_split_max_depth: int = Field(default=0, ge=0, le=4)
    # 같은 입력 재사용 (W1-3). 켜면 같은 매장·같은 재사용 키로 파싱에 성공한 지난 응답이
    # 있을 때 모델을 부르지 않고 그 응답을 되쓴다(원장에 REUSED·비용 0). 기본 켜짐 —
    # 입력·모델·프롬프트·설정이 모두 같을 때만 적중하므로 제품 경로에서 켜 둔다(2026-09-29 사용자 결정).
    # 키 자체는 꺼져 있어도 원래 응답 행에 언제나 남긴다 — 켜는 순간부터 찾을 수 있다
    extract_reuse_enabled: bool = True
    # 평가 실행(EVALUATION·extraction_run_id)은 모델의 흔들림을 잰다. 지난 응답을 되쓰면
    # 반복(D17/D18)이 전부 같아져 변동 측정이 무너진다. 이 플래그를 따로 켤 때만 재사용한다
    extract_reuse_for_evaluation: bool = False
    # W1-4 근거 위치 표지. 켜면 사실 추출에 쪽·메시지 번호(page·line)를 받는다 —
    # 위치 표지 프롬프트(extract_facts_locator.ko.txt)·스키마(LocatedFactExtractionResult)·
    # 카톡 `[#N]` 표지를 쓰고, 서버가 그 번호를 검사해 PAGE·LINE 위치로 남긴다.
    # 끄면 추출 요청이 이전과 같다(D16 비교 기준 유지). 근거 위치 표 기록·서버 검사는 플래그와 무관하다
    extract_locator_hints: bool = False
    # W1-4 근거 없는 단위·규격 값 비우기. 기본 꺼짐 — 판정만 근거 위치 행(check_flags)과
    # unresolved 에 남기고 값은 그대로 둔다. 글만 있는 입력(음성 전사·카톡·TEXT PDF)의 판정은
    # 오탐이 있고, 값을 비우면 content_hash 가 바뀌며 HOT/ICE 가 합쳐질 수 있다(D19·D16).
    # 켜면 글만 있는 입력의 근거 없는 값을 비운다(첨부가 있는 입력은 켜도 남기고 표시만 한다)
    extract_clear_ungrounded_values: bool = False
    # Files API 업로드가 ACTIVE 가 될 때까지 기다리는 한도·폴링 간격 (gemini.py 에서 옮김)
    gemini_file_active_timeout_sec: int = Field(default=600, ge=0)
    gemini_file_poll_sec: int = Field(default=5, ge=0)

    # 추출 온도. 답변 생성은 D12 로 0.0 이 못 박혀 있는데 추출만 0.2 였다.
    # 근거가 문서 어디에도 없었고, 같은 자료를 두 번 돌리면 손실률이 8%p 가까이 흔들렸다.
    # 측정 도구의 오차가 측정하려는 효과보다 크면 실험이 성립하지 않으므로 0.0 을 기본으로 둔다.
    # 0.2 단위로 올려가며 다양성 이득이 있는지는 하네스로 확인한다
    extract_temperature: float = 0.0
    # PDF 를 모델에 어떻게 넣는가. A/B/C 실험용 (W1 결함3 후속).
    #   TEXT   — pypdf 텍스트만. 기존 동작이자 대조군. 표 구조가 깨질 수 있다
    #   FILE   — PDF 원본만. Gemini 가 페이지를 직접 읽는다
    #   BOTH   — 둘 다. 잃는 것이 없는 대신 페이지마다 비용이 든다
    #   HYBRID — 텍스트 + 그림이 있는 페이지가 있을 때만 원본을 붙인다 (비용 절충)
    # 어느 쪽이 정확한지는 측정 전까지 모른다. 기본값은 결함3 수정본인 HYBRID 다.
    # TEXT 는 그 수정 이전 동작이므로 실험에서 대조군으로만 명시 지정한다.
    pdf_input_mode: Literal["TEXT", "FILE", "BOTH", "HYBRID"] = "HYBRID"

    storage_bucket: str = "sources"      # 원본 파일 버킷. 비공개
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_db_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    # asyncpg 연결 풀 크기. 늘리기 전에 모델 호출 중 연결을 쥐고 있는 경로가 없는지 먼저 확인한다
    db_pool_min_size: int = Field(default=1, ge=1)
    db_pool_max_size: int = Field(default=10, ge=1)

    jwt_secret: str = "dev-only-change-me-32bytes-minimum"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # 앱 내부 알림은 키 없이도 동작한다. 세 값이 모두 있을 때만 Web Push를 추가 전송한다.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    push_guide_version: str = "push-guide-v1"

    @model_validator(mode="after")
    def _check_db_pool_sizes(self) -> "Settings":
        # 최소가 최대보다 크면 asyncpg 가 시작 시점에 실패한다. 설정 단계에서 먼저 막는다
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("db_pool_min_size must be <= db_pool_max_size")
        # 겹침이 창보다 크거나 같으면 구간마다 앞 구간 전체를 다시 본다
        if self.video_segment_sec > 0 and self.video_segment_overlap_sec >= self.video_segment_sec:
            raise ValueError("video_segment_overlap_sec must be < video_segment_sec")
        return self

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
