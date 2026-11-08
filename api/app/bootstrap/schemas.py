from typing import Literal

from pydantic import BaseModel


class BootstrapUser(BaseModel):
    user_id: int
    role: Literal["OWNER", "STAFF"] | None
    name: str
    # 프로필 사진(비공개 버킷의 잠깐 읽는 URL). 없으면 null
    avatar_url: str | None = None


class BootstrapStore(BaseModel):
    store_id: int
    store_name: str
    guide_completed: bool
    category_version: int


class BootstrapBadges(BaseModel):
    waiting_questions: int = 0
    pending_cards: int = 0


class BootstrapResponse(BaseModel):
    user: BootstrapUser
    store: BootstrapStore | None
    badges: BootstrapBadges
    default_destination: str
