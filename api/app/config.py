"""공용 — 환경변수 로딩. 수정 전 팀 합의."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    # 추출 온도. 답변 생성은 D12 로 0.0 이 못 박혀 있는데 추출만 0.2 였다.
    # 근거가 문서 어디에도 없었고, 같은 자료를 두 번 돌리면 손실률이 8%p 가까이 흔들렸다.
    # 측정 도구의 오차가 측정하려는 효과보다 크면 실험이 성립하지 않으므로 0.0 을 기본으로 둔다.
    # 0.2 단위로 올려가며 다양성 이득이 있는지는 하네스로 확인한다
    extract_temperature: float = 0.0

    storage_bucket: str = "sources"      # 원본 파일 버킷. 비공개
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_db_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    jwt_secret: str = "dev-only-change-me-32bytes-minimum"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # 앱 내부 알림은 키 없이도 동작한다. 세 값이 모두 있을 때만 Web Push를 추가 전송한다.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    push_guide_version: str = "push-guide-v1"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
