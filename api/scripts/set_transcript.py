"""전사문을 DB 에 넣는다. STT 없이 추출부터 개발할 때 쓴다 (가이드 8장 --skip-stt).

    # 새 자료를 만들면서 전사문 주입
    python scripts/set_transcript.py --file data/sample_transcript.ko.txt

    # 기존 자료의 전사문 교체
    python scripts/set_transcript.py --source-id 7 --file my.txt

전사문이 있으면 파이프라인이 STT 를 건너뛴다. 다시 전사시키려면 --clear 로 비운다.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402

# 타임스탬프 대본 형식 (음성 대체용)
#   00:03–00:05  [c2] 언더카운터 냉장고
#     "머신 아래 작업대 하부가 언더카운터 냉장고고, 우유는 여기 들어있어요."
_CUE = re.compile(
    r"^(?P<t>\d{1,2}:\d{2})\s*[–\-~]\s*\d{1,2}:\d{2}\s+"
    r"\[(?P<id>c\d+)\]\s*(?P<label>.*)$")
_OPEN = re.compile(r'^\s*["\u201c](?P<say>.*)$')


def parse_script(raw: str) -> tuple[str, int]:
    """대본에서 실제 발화만 뽑는다. 반환 (전사문, 구간 수).

    무음 표시·규칙 안내·[cN] 마커·※ 주석이 전사문에 섞이면 추출 품질 비교가
    무의미해진다. 대사는 여러 줄에 걸쳐 있고 닫는 따옴표에서 끝난다.
    대본 형식이 아니면 (원문, 0) 을 돌려준다.
    """
    lines = raw.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    cue: str | None = None
    buf: list[str] | None = None

    for line in lines:
        stripped = line.strip()

        if buf is not None:                       # 대사 이어받는 중
            if stripped.startswith("※"):          # 작성자 주석은 대사가 아니다
                continue
            closed = stripped.endswith('"') or stripped.endswith("\u201d")
            buf.append(stripped.rstrip('"\u201d'))
            if closed:
                out.append(f"[{cue}] " + " ".join(x for x in buf if x))
                cue, buf = None, None
            continue

        if (m := _CUE.match(stripped)):
            cue = m.group("t")
            continue

        if cue and (m := _OPEN.match(line)):
            body = m.group("say").strip()
            closed = body.endswith('"') or body.endswith("\u201d")
            buf = [body.rstrip('"\u201d')]
            if closed:
                out.append(f"[{cue}] " + buf[0])
                cue, buf = None, None

    if not out:
        return raw.strip(), 0
    return "\n".join(out), len(out)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, help="전사문 텍스트 파일")
    ap.add_argument("--source-id", type=int, help="없으면 새 자료를 만든다")
    ap.add_argument("--slug", default="demo-cafe")
    ap.add_argument("--title", default="전사문 주입 (STT 생략)")
    ap.add_argument("--clear", action="store_true", help="전사문을 비운다 (STT 다시 시키기)")
    args = ap.parse_args()

    if not args.clear and not args.file:
        print("--file 또는 --clear 중 하나는 필요하다", file=sys.stderr)
        return 2

    text = "" if args.clear else args.file.read_text(encoding="utf-8").strip()
    if not args.clear and not text:
        print(f"{args.file} 이 비어 있다", file=sys.stderr)
        return 2

    if not args.clear:
        text, cues = parse_script(text)
        if cues:
            print(f"타임스탬프 대본 인식 — 발화 {cues}구간만 추출 (무음·마커 제거)")

    s = get_settings()
    conn = await asyncpg.connect(s.supabase_db_url)
    try:
        store = await conn.fetchrow(
            "select s.store_id, m.user_id from stores s "
            "join store_members m on m.store_id = s.store_id and m.member_role = 'OWNER' "
            "where s.store_slug = $1", args.slug)
        if store is None:
            print(f"'{args.slug}' 매장이 없다. 시드를 먼저 적용하라", file=sys.stderr)
            return 1

        source_id = args.source_id
        if source_id is None:
            async with conn.transaction():
                source_id = await conn.fetchval(
                    "insert into sources (store_id, uploaded_by, source_type, title, status) "
                    "values ($1, $2, 'VOICE', $3, 'UPLOADED') returning source_id",
                    store["store_id"], store["user_id"], args.title)
                await conn.execute(
                    "insert into source_voice (source_id, audio_format, duration_sec, record_method) "
                    "values ($1, 'm4a', 0, 'UPLOAD')", source_id)
            print(f"새 자료 생성: source_id={source_id}")
        else:
            owned = await conn.fetchval(
                "select 1 from sources where store_id = $1 and source_id = $2",
                store["store_id"], source_id)
            if not owned:
                print(f"source {source_id} 는 이 매장 자료가 아니다", file=sys.stderr)
                return 1

        await conn.execute(
            "update source_voice set transcript = $2, stt_model = $3 where source_id = $1",
            source_id, text or None, None if args.clear else "manual")
    finally:
        await conn.close()

    if args.clear:
        print(f"source {source_id} 전사문 삭제 — 다음 처리에서 STT 를 다시 돈다")
    else:
        print(f"source {source_id} 전사문 {len(text)}자 주입 완료")
        print(f"  다음: curl -X POST localhost:8000/ingest/process "
              f"-H \"Authorization: Bearer $ASKBUDDY_TOKEN\" "
              f"-H 'Content-Type: application/json' -d '{{\"source_id\":{source_id}}}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
