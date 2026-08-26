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
    # 이 점수를 넘으면 낱말이 안 겹쳐도 통과 (D12)
    retrieval_strong_score: float = 0.62
    frame_interval_sec: int = 3

    # ingest (준혁) — mock: LLM 미호출(M1 기본값) / real: Gemini 호출
    ingest_mode: Literal["mock", "real"] = "mock"
    gemini_model: str = "gemini-3.6-flash"
    stt_model: str = "whisper-1"

    storage_bucket: str = "sources"      # 원본 파일 버킷. 비공개
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_db_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    jwt_secret: str = "dev-only-change-me-32bytes-minimum"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
