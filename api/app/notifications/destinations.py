"""알림·이동 주소의 단일 출처.

웹 화면 주소가 바뀌면 여기만 고친다. 옛 주소(/owner/questions/v2, /staff/chat/v2 등)는
이미 저장된 알림 때문에 웹이 리다이렉트로 받아 주지만, 새로 만드는 알림은 새 주소를 바로 준다.
"""

from urllib.parse import quote

OWNER_HOME = "/owner"
OWNER_QUESTIONS = "/owner/questions"
OWNER_MEMBERS = "/owner/members"
STAFF_HOME = "/staff"
STAFF_RECIPES = "/staff/recipes"
STAFF_ASK = "/staff/ask"


def owner_question(question_id: int) -> str:
    """사장님이 답할 질문 화면."""
    return f"{OWNER_QUESTIONS}/{question_id}"


def owner_job_cards(job_id: int) -> str:
    """이번 작업에서 만든 카드만 모아 본다."""
    return f"/owner/cards?status=all&job_id={job_id}"


def staff_session(session_id: str | None) -> str:
    """직원 버디 대화. 대화 번호가 없으면 새 대화 화면."""
    return f"{STAFF_ASK}?session_id={quote(session_id, safe='')}" if session_id else STAFF_ASK
