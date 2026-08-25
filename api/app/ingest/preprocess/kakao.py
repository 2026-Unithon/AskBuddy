"""준혁 — 카카오톡 대화 내보내기(txt) 파서 (M4).

안드로이드·iOS 두 형식을 모두 받는다. LLM 을 쓰지 않는다 — 정규식으로 충분하고,
잘못 파싱되면 조용히 이상한 카드가 나오는 것보다 여기서 세는 편이 낫다.

안드로이드
    2026년 8월 25일 오전 9:12, 사장님 : 우유는 냉장고 2단에 있어요
iOS
    2026. 8. 25. 오전 9:12, 사장님 : 우유는 냉장고 2단에 있어요
"""
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_ROOM = re.compile(r"^(.*?)\s*님과 카카오톡 대화$|^(.*?)\s*카카오톡 대화$", re.M)
_ANDROID = re.compile(
    r"^(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일\s*"
    r"(?P<ampm>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*"
    r"(?P<who>[^:]+?)\s*:\s*(?P<msg>.*)$")
_IOS = re.compile(
    r"^(?P<y>\d{4})\.\s*(?P<mo>\d{1,2})\.\s*(?P<d>\d{1,2})\.\s*"
    r"(?P<ampm>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*"
    r"(?P<who>[^:]+?)\s*:\s*(?P<msg>.*)$")
# 사진·이모티콘·입퇴장 같은 내용 없는 줄
_NOISE = re.compile(r"^(사진|동영상|이모티콘|삭제된 메시지입니다\.?|"
                    r".*님이 (들어왔습니다|나갔습니다)\.?)$")


def _ts(m: re.Match) -> datetime:
    h = int(m.group("h")) % 12
    if m.group("ampm") == "오후":
        h += 12
    return datetime(int(m.group("y")), int(m.group("mo")), int(m.group("d")),
                    h, int(m.group("mi")), tzinfo=KST)


def parse(raw: str) -> dict:
    """반환: room_name, participants, message_count, period_start/end, parsed_text"""
    lines = raw.replace("\r\n", "\n").split("\n")

    room = None
    if (m := _ROOM.search(raw)):
        room = (m.group(1) or m.group(2) or "").strip() or None

    messages: list[tuple[datetime, str, str]] = []
    for line in lines:
        m = _ANDROID.match(line) or _IOS.match(line)
        if not m:
            # 여러 줄 메시지의 이어지는 줄은 직전 메시지에 붙인다.
            # 단 '사진'·'이모티콘' 같은 내용 없는 줄은 붙이지 않는다 —
            # 타임스탬프가 없어 여기로 들어오므로 앞 메시지를 오염시킨다
            cont = line.strip()
            if messages and cont and not cont.startswith("---") and not _NOISE.match(cont):
                t, who, msg = messages[-1]
                messages[-1] = (t, who, f"{msg}\n{cont}")
            continue
        text = m.group("msg").strip()
        if not text or _NOISE.match(text):
            continue
        messages.append((_ts(m), m.group("who").strip(), text))

    if not messages:
        raise RuntimeError(
            "카카오톡 대화를 한 건도 파싱하지 못했다. "
            "'대화 내용 내보내기' 로 받은 txt 인지 확인하라"
        )

    participants = sorted({who for _, who, _ in messages})
    parsed_text = "\n".join(
        f"[{t.strftime('%m-%d %H:%M')}] {who}: {msg}" for t, who, msg in messages)

    logger.info("카톡 파싱 %d건 참여자 %d명 (%s ~ %s)",
                len(messages), len(participants),
                messages[0][0].date(), messages[-1][0].date())

    return {
        "room_name": room,
        "participants": participants,
        "message_count": len(messages),
        "period_start": messages[0][0],
        "period_end": messages[-1][0],
        "parsed_text": parsed_text,
    }
