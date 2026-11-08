"""프로필 사진(2026-11-08 사용자: 연필 하나로 사진·이름·매장 이름). 비공개 avatars 버킷, 서명 URL 로만."""
import asyncio

import pytest

from app.bootstrap import profile, router as bootstrap_router
from app.errors import ApiError


def test_avatar_path_is_scoped_to_store_and_user():
    path = profile.avatar_object_path(store_id=3, user_id=9, content_type="image/png")
    assert path.startswith("avatars/3/9/") and path.endswith(".png")


def test_avatar_path_rejects_non_image():
    with pytest.raises(ValueError):
        profile.avatar_object_path(store_id=3, user_id=9, content_type="application/pdf")


def test_owned_path_check():
    assert profile.owns_avatar_path("avatars/3/9/0123456789abcdef0123456789abcdef.png", store_id=3, user_id=9)
    assert not profile.owns_avatar_path("avatars/3/8/0123456789abcdef0123456789abcdef.png", store_id=3, user_id=9)  # 다른 사람
    assert not profile.owns_avatar_path("avatars/4/9/0123456789abcdef0123456789abcdef.png", store_id=3, user_id=9)  # 다른 매장
    assert not profile.owns_avatar_path("avatars/3/9/../8/0123456789abcdef0123456789abcdef.png", store_id=3, user_id=9)
    assert not profile.owns_avatar_path("sources/3/9/0123456789abcdef0123456789abcdef.png", store_id=3, user_id=9)


class _Db:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


def test_upload_url_route_signs_scoped_path(monkeypatch):
    async def fake_sign(path):
        return f"https://storage.test/upload/{path}"
    monkeypatch.setattr(bootstrap_router, "create_signed_upload_url", fake_sign)
    req = bootstrap_router.AvatarUploadRequest(content_type="image/jpeg", size=1000)
    res = asyncio.run(bootstrap_router.avatar_upload_url(req, {"user_id": 9, "store_id": 3, "role": "STAFF"}))
    assert res.path.startswith("avatars/3/9/") and res.upload_url.endswith(res.path)


def test_upload_url_rejects_big_file():
    with pytest.raises(ValueError):
        bootstrap_router.AvatarUploadRequest(content_type="image/jpeg", size=6 * 1024 * 1024)


def test_set_avatar_rejects_other_users_path():
    db = _Db()
    req = bootstrap_router.AvatarSetRequest(path="avatars/3/8/0123456789abcdef0123456789abcdef.png")
    with pytest.raises(ApiError) as caught:
        asyncio.run(bootstrap_router.set_avatar(req, db, {"user_id": 9, "store_id": 3, "role": "STAFF"}))
    assert caught.value.status_code == 403
    assert db.calls == []


def test_set_avatar_saves_own_path():
    db = _Db()
    req = bootstrap_router.AvatarSetRequest(path="avatars/3/9/0123456789abcdef0123456789abcdef.png")
    asyncio.run(bootstrap_router.set_avatar(req, db, {"user_id": 9, "store_id": 3, "role": "STAFF"}))
    sql, args = db.calls[0]
    assert "avatar_path" in sql and args == (9, "avatars/3/9/0123456789abcdef0123456789abcdef.png")
