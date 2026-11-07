"""한 번 호출 시험 세트의 음성 사례를 whisper 로 한 번 전사해 transcript.txt 로 둔다 (유료, 사용자 승인 뒤).

이미 전사본이 있는 사례는 건너뛴다. 실행마다 길이·비용을 세트의 spend.jsonl 에 남긴다.

    cd api && python scripts/transcribe_single_call_set.py --set eval/data/single-call-set --confirm-paid
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.ingest.preprocess.audio import probe, transcribe_detailed

# whisper-1 공시 요율(USD/분). 원가 추정용이며 청구 금액이 아니다
WHISPER_USD_PER_MIN = 0.006


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--confirm-paid", action="store_true")
    args = ap.parse_args()
    if not args.confirm_paid:
        raise SystemExit("유료 호출이다. 사용자 승인 뒤 --confirm-paid 로 실행한다")
    model = get_settings().stt_model
    spend = args.set / "spend.jsonl"
    total = 0.0
    for meta_path in sorted((args.set / "cases").glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["format"] != "AUDIO_TRANSCRIPT":
            continue
        case_dir = meta_path.parent
        if (case_dir / "transcript.txt").exists():
            print(f"{meta['case_id']}: 전사본 있음, 건너뜀")
            continue
        audio = case_dir / meta["audio"]
        duration = (await probe(audio))["duration_sec"]
        text, _, used = await transcribe_detailed(audio)
        (case_dir / "transcript.txt").write_text(text, encoding="utf-8")
        meta["input_status"] = "READY"
        meta["transcript_model"] = used
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        cost = duration / 60 * WHISPER_USD_PER_MIN
        total += cost
        row = {"at": datetime.now(timezone.utc).isoformat(), "step": "transcribe", "case_id": meta["case_id"],
               "model": model, "audio_sec": duration, "chars": len(text), "est_usd": round(cost, 5)}
        with spend.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{meta['case_id']}: {duration}s → {len(text)}자, 약 ${cost:.4f}")
    print(f"이번 전사 합계 약 ${total:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
