"""계획 8 Task 7: 확인 문구 검사(화면 우회 방지)."""
import pytest

from app.bootstrap.account_router import ConfirmRequest, check_confirm
from app.errors import ApiError


def test_confirm_must_match_exactly_ignoring_edges():
    check_confirm(ConfirmRequest(confirm="  퇴사하겠습니다 "), "퇴사하겠습니다")
    with pytest.raises(ApiError) as err:
        check_confirm(ConfirmRequest(confirm="퇴사 하겠습니다"), "퇴사하겠습니다")
    assert err.value.code == "CONFIRM_MISMATCH"
