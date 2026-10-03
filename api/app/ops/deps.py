"""운영자 인증. 제품 토큰과 audience 로 갈라진다.

제품 API 의 get_claims 는 audience 없이 decode 한다. PyJWT 는 그때 aud 가 있는 토큰을
InvalidAudienceError 로 거부하므로, 운영자 토큰으로 매장 API 를 부를 수 없다.
운영자는 매장에 속하지 않는다. 요청마다 users.role 을 다시 읽어 회수된 역할을 즉시 막는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException

from app.config import get_settings
from app.deps import Db, _claim_id, create_token

OPS_AUDIENCE = "askbuddy-ops"
OPS_ROLE = "OPERATOR"


def create_operator_token(user_id: int) -> str:
    s = get_settings()
    return create_token({
        "user_id": user_id,
        "role": OPS_ROLE,
        "aud": OPS_AUDIENCE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.ops_token_expire_minutes),
    })


# store-isolation-ok: 운영자는 매장 밖 계정이라 store_id 가 없다
async def get_operator_id(db: Db, authorization: Annotated[str | None, Header()] = None) -> int:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    s = get_settings()
    try:
        claims = jwt.decode(authorization[7:], s.jwt_secret, algorithms=[s.jwt_algorithm],
                            audience=OPS_AUDIENCE, options={"require": ["exp", "aud"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, "invalid token") from e
    if claims.get("role") != OPS_ROLE:
        raise HTTPException(401, "invalid token")
    user_id = _claim_id(claims, "user_id")
    # store-isolation-ok: 운영자는 매장에 속하지 않는다. users 역할만 재확인한다
    row = await db.fetchrow("select role from users where user_id = $1", user_id)
    if not row or row["role"] != OPS_ROLE:
        raise HTTPException(403, "operator role required")
    return user_id


OperatorId = Annotated[int, Depends(get_operator_id)]
