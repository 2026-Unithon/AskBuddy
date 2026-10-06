"""공급자 호출 결과. 모든 공급자가 같은 형태로 돌려준다."""
from typing import NamedTuple


class CallResult(NamedTuple):
    """모델 호출 한 번의 결과.

    finish_reason — 공급자 종료 사유를 STOP·MAX_TOKENS 등으로 맞춘 문자열. 못 받으면 None.
    raw_response_id — 원래 응답 행(extraction_raw_responses). 기록하지 않았으면 None.
    reused — 모델을 부르지 않고 같은 입력의 지난 성공 응답을 되썼다 (W1-3).
    """

    text: str
    usage: dict
    finish_reason: str | None
    raw_response_id: int | None = None
    reused: bool = False
