"""한 번 호출 추출 시험 — 추출(Sonnet 5.5) → 판정(Opus 5.5) → 보고 (유료, 사용자 승인 뒤).

추출은 제품 지시문(render_facts_prompt)과 제품 응답 형식(FactExtractionResult)을 그대로 쓰고 모델만 바꾼다.
판정은 정답 사실마다 결과 어디에든 언급됐는지만 본다(README S3, 놓침만 잰다).

    cd api && python scripts/run_single_call_eval.py --set eval/data/single-call-set --run r1 --confirm-paid
    cd api && python scripts/run_single_call_eval.py --set eval/data/single-call-set --run r1 --report-only

산출물: <set>/runs/<run>/<case_id>/{extraction.json,judge.json}, <set>/runs/<run>/report.json, <set>/spend.jsonl

`--product` (2026-11-07): 추출을 **제품 경로 그대로** 돈다 — 제품 전처리와 같은 입력(PDF 글자층·쪽 표지·HYBRID 첨부,
카톡 메시지 번호, 사진 안내문+그림)을 `single_call.extract_single`(줄 번호·분류 꼬리·끊김 검사·이어서 뽑기 최대 3번)에
넣는다. 비용은 Claude 호출 자리를 감싸 잰다. 시도 수·처리 안 된 범위를 extraction.json 에 함께 남긴다.
"""
import argparse
import asyncio
import base64
import contextlib
import contextvars
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import get_settings
from app.ingest.extract.gemini import render_facts_prompt
from app.ingest.preprocess.docx import read_docx, to_text
from app.ingest.schemas import FactExtractionResult

EXTRACT_MODEL = "claude-sonnet-5-5"
JUDGE_MODEL = "claude-opus-5-5"
# 공시 요율(USD / 100만 토큰, 입력·출력). 원가 추정용이며 청구 금액이 아니다(2026-10 기준)
PRICE = {EXTRACT_MODEL: (2.0, 10.0), JUDGE_MODEL: (4.0, 20.0)}
SOURCE_TYPE = {"DOC_IMAGE": "SCAN", "CHAT": "KAKAO", "AUDIO_TRANSCRIPT": "VOICE",
               "DOC_TEXT": "DOCX", "OWNER_TEXT": "OWNER_TEXT",
               "PHOTO": "SCAN", "CHAT_IMAGE": "KAKAO", "PDF_TEXT": "SCAN"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
JUDGE_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "judge_single_call_recall.ko.txt"
CONCURRENCY = 4


class Verdict(BaseModel):
    fact_id: str
    verdict: Literal["MENTIONED", "MENTIONED_VALUE_DIFFERS", "MISSING"]
    evidence: list[str]
    note: str


class JudgeResult(BaseModel):
    verdicts: list[Verdict]


class Spend:
    """실행별·누적 비용 기록. 상한을 넘으면 다음 호출 전에 멈춘다."""

    def __init__(self, path: Path, run: str, max_usd: float):
        self.path, self.run, self.max_usd, self.total = path, run, max_usd, 0.0

    def check(self) -> None:
        if self.total >= self.max_usd:
            raise SystemExit(f"이번 실행 비용 추정 ${self.total:.2f} 이 상한 ${self.max_usd:.2f} 에 닿아 멈춘다")

    def add(self, step: str, case_id: str, model: str, usage, seconds: float) -> None:
        pin, pout = PRICE[model]
        usd = usage.input_tokens / 1e6 * pin + usage.output_tokens / 1e6 * pout
        self.total += usd
        row = {"at": datetime.now(timezone.utc).isoformat(), "run": self.run, "step": step, "case_id": case_id,
               "model": model, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
               "seconds": round(seconds, 1), "est_usd": round(usd, 5)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_input(case_dir: Path, meta: dict) -> tuple[str, list[dict]]:
    """(지시문에 넣을 글, 앞에 붙일 문서 블록)."""
    path = case_dir / meta["input"]
    if path.suffix == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        doc = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        return "(첨부한 PDF 문서가 자료다)", [doc]
    if path.suffix in IMAGE_TYPES:
        data = base64.standard_b64encode(path.read_bytes()).decode()
        img = {"type": "image", "source": {"type": "base64", "media_type": IMAGE_TYPES[path.suffix], "data": data}}
        return "(첨부한 이미지가 자료다)", [img]
    if path.suffix == ".docx":
        return to_text(read_docx(path)), []
    return path.read_text(encoding="utf-8"), []


async def call(client: AsyncAnthropic, *, model: str, content: list[dict], output_format, effort: str):
    async with client.messages.stream(
        model=model, max_tokens=64000, messages=[{"role": "user", "content": content}],
        output_format=output_format, output_config={"effort": effort},
    ) as stream:
        msg = await stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"모델이 거절했다: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("출력이 max_tokens 에서 잘렸다")
    return msg


def render_extraction(result: dict, menu_map: dict[str, str]) -> str:
    lines = []
    for a in result["assertions"]:
        bits = [a["local_ref"], f"원문: {a['original_assertion']}",
                f"{a['subject']}{' [' + a['variant'] + ']' if a.get('variant') else ''} / {a['attribute']} = "
                f"{a['value']}{' ' + a['unit'] if a.get('unit') else ''}"]
        if a.get("polarity") == "NEGATE":
            bits.append("부정(하지 않는다)")
        if a.get("conditions"):
            bits.append("조건: " + "; ".join(a["conditions"]))
        if a.get("exceptions"):
            bits.append("예외: " + "; ".join(a["exceptions"]))
        lines.append(" | ".join(bits))
    for u in result.get("unresolved", []):
        lines.append(f"(미해결) {u}")
    text = "\n".join(lines) or "(추출 결과 없음)"
    # 원본 메뉴명을 정답지 메뉴명으로 바꾼다(store-a). 판정만을 위한 치환이다
    for original, mapped in menu_map.items():
        text = text.replace(original, mapped)
    return text


def render_gold(facts: list[dict]) -> str:
    return "\n".join(
        f"{f['fact_id']} | {f['subject']}{' [' + f['variant'] + ']' if f.get('variant') else ''} | "
        f"{f['attribute']} = {f['value']}" for f in facts)


def product_input(case_dir: Path, meta: dict) -> tuple[str, list[Path], str]:
    """제품 전처리(pipeline._preprocess_*)와 같은 입력 글·첨부·자료 종류를 만든다."""
    from app.ingest.preprocess import document, kakao

    path = case_dir / meta["input"]
    fmt = meta["format"]
    if fmt == "OWNER_TEXT":
        return path.read_text(encoding="utf-8"), [], "OWNER_TEXT"
    if fmt == "AUDIO_TRANSCRIPT":
        return path.read_text(encoding="utf-8"), [], "VOICE"
    if fmt == "CHAT":
        return kakao.parse(path.read_text(encoding="utf-8"), message_numbers=True)["parsed_text"], [], "KAKAO"
    if fmt == "CHAT_IMAGE":
        return "(카카오톡 대화 캡처. 첨부한 그림을 읽고 판단할 것)", [path], "KAKAO"
    if path.suffix == ".docx":
        return to_text(read_docx(path)), [], "SCAN"
    if path.suffix == ".pdf":
        read = document.read_pdf(path)
        if not read.text:
            return "(텍스트 레이어 없는 스캔본. 첨부한 문서를 읽고 판단할 것)", [path], "SCAN"
        if read.visual_pages:
            pages = ", ".join(f"{n}쪽" for n in read.visual_pages)
            return (f"{read.text}\n\n(위 글에 없는 내용이 {pages} 에 그림·표로 있다. "
                    f"첨부한 문서의 해당 쪽을 읽고 판단할 것)"), [path], "SCAN"
        return read.text, [], "SCAN"
    return "(이미지 자료. 첨부한 그림을 읽고 판단할 것)", [path], "SCAN"


# 지금 처리 중인 사례 id. 동시에 도는 사례마다 따로 보인다(asyncio task 마다 복사된다)
CURRENT_CASE: contextvars.ContextVar[str] = contextvars.ContextVar("case", default="?")


@contextlib.contextmanager
def metering(spend: Spend):
    """Claude 추출 호출 자리를 **실행 전체에서 한 번만** 감싸 비용을 적는다.

    사례마다 patch 를 열고 닫으면 동시에 도는 사례끼리 감싸기가 겹쳐 한 호출이 여러 번 기록된다
    (2026-11-07 p1 에서 82행/실제 23회). 사례는 CURRENT_CASE 로 가른다.
    """
    from unittest.mock import patch

    from app.ingest import extract as extract_mod
    from app.ingest.providers import anthropic_call

    real_call = anthropic_call.call_extract

    async def metered(model, prompt, media, schema, **kw):
        spend.check()
        started = time.perf_counter()
        reply = await real_call(model, prompt, media, schema, **kw)
        usage = type("U", (), {"input_tokens": reply.usage.get("prompt_tokens", 0),
                               "output_tokens": reply.usage.get("completion_tokens", 0)})()
        spend.add("extract-product", CURRENT_CASE.get(), EXTRACT_MODEL, usage, time.perf_counter() - started)
        return reply

    real_settings = get_settings().model_copy(update={"ingest_mode": "real"})
    with patch.object(anthropic_call, "call_extract", metered), \
         patch.object(extract_mod, "get_settings", lambda: real_settings):
        yield


async def extract_product(spend: Spend, case_dir: Path, meta: dict) -> dict:
    """제품 한 번 호출로 뽑는다. 비용은 metering() 이 적는다."""
    from app.ingest.extract import single_call

    CURRENT_CASE.set(meta["case_id"])
    text, media, source_type = product_input(case_dir, meta)
    outcome = await single_call.extract_single(
        source_id=0, source_type=source_type, text=text, media=media, glossary=[])
    result = outcome.result.model_dump(exclude={"assertions": {"__all__": {"segment_id"}}}) \
        if outcome.result is not None else {"assertions": [], "unresolved": []}
    return {**result, "_attempts": outcome.attempts, "_unprocessed": outcome.unprocessed}


async def run_case(client, sem, spend: Spend, case_dir: Path, out_dir: Path, product: bool = False) -> None:
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    gold = json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))
    menu_map = {}
    if meta.get("menu_map"):
        menu_map = {k: v for k, v in json.loads((case_dir / meta["menu_map"]).read_text(encoding="utf-8")).items()
                    if not k.startswith("_")}
    out = out_dir / meta["case_id"]
    out.mkdir(parents=True, exist_ok=True)
    async with sem:
        if not (out / "extraction.json").exists() and product:
            result = await extract_product(spend, case_dir, meta)
            (out / "extraction.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not (out / "extraction.json").exists():
            spend.check()
            text, blocks = load_input(case_dir, meta)
            prompt = render_facts_prompt(source_type=SOURCE_TYPE[meta["format"]], text=text, glossary=[])
            started = time.perf_counter()
            msg = await call(client, model=EXTRACT_MODEL, content=[*blocks, {"type": "text", "text": prompt}],
                             output_format=FactExtractionResult, effort="high")
            spend.add("extract", meta["case_id"], EXTRACT_MODEL, msg.usage, time.perf_counter() - started)
            result = msg.parsed_output.model_dump(exclude={"assertions": {"__all__": {"segment_id"}}})
            (out / "extraction.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
        if not (out / "judge.json").exists():
            spend.check()
            prompt = (JUDGE_PROMPT.read_text(encoding="utf-8")
                      .replace("{gold}", render_gold(gold["facts"]))
                      .replace("{extraction}", render_extraction(result, menu_map)))
            started = time.perf_counter()
            msg = await call(client, model=JUDGE_MODEL, content=[{"type": "text", "text": prompt}],
                             output_format=JudgeResult, effort="medium")
            spend.add("judge", meta["case_id"], JUDGE_MODEL, msg.usage, time.perf_counter() - started)
            judged = msg.parsed_output.model_dump()
            got = {v["fact_id"] for v in judged["verdicts"]}
            want = {f["fact_id"] for f in gold["facts"]}
            if got != want:
                # 판정이 정답을 빠뜨리거나 지어냈다 — 분모가 흔들리므로 저장하지 않고 멈춘다
                raise RuntimeError(f"{meta['case_id']}: 판정 fact_id 불일치 빠짐={want - got} 추가={got - want}")
            (out / "judge.json").write_text(json.dumps(judged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{meta['case_id']}: 완료")


def report(set_dir: Path, out_dir: Path) -> dict:
    groups: dict[str, dict] = defaultdict(lambda: {"total": 0, "mentioned": 0, "value_differs": 0,
                                                    "must_total": 0, "must_mentioned": 0})
    missing = []
    for case_dir in sorted((set_dir / "cases").iterdir()):
        judge_path = out_dir / case_dir.name / "judge.json"
        if not judge_path.exists():
            continue
        meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
        gold = {f["fact_id"]: f for f in json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))["facts"]}
        for v in json.loads(judge_path.read_text(encoding="utf-8"))["verdicts"]:
            hit = v["verdict"] != "MISSING"
            must = gold[v["fact_id"]].get("must_have", False)
            for key in ("ALL", f"case:{meta['case_id']}", f"format:{meta['format']}",
                        f"logic:{meta['logic']}", f"origin:{meta['origin']}"):
                g = groups[key]
                g["total"] += 1
                g["mentioned"] += hit
                g["value_differs"] += v["verdict"] == "MENTIONED_VALUE_DIFFERS"
                g["must_total"] += must
                g["must_mentioned"] += must and hit
            if not hit:
                f = gold[v["fact_id"]]
                missing.append({"fact_id": v["fact_id"], "case_id": meta["case_id"], "must_have": must,
                                "fact": f"{f['subject']} / {f['attribute']} = {f['value']}"})
    for g in groups.values():
        g["recall"] = round(g["mentioned"] / g["total"], 4) if g["total"] else None
        g["must_recall"] = round(g["must_mentioned"] / g["must_total"], 4) if g["must_total"] else None
    rep = {"groups": dict(sorted(groups.items())), "missing": missing}
    (out_dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--confirm-paid", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--max-usd", type=float, default=10.0)
    ap.add_argument("--only", nargs="*", help="이 사례만 돌린다")
    ap.add_argument("--product", action="store_true", help="제품 한 번 호출 경로(extract_single)로 뽑는다")
    args = ap.parse_args()
    out_dir = args.set / "runs" / args.run
    if not args.report_only:
        if not args.confirm_paid:
            raise SystemExit("유료 호출이다. 사용자 승인 뒤 --confirm-paid 로 실행한다")
        index = json.loads((args.set / "index.json").read_text(encoding="utf-8"))
        todo = [r["case_id"] for r in index if r["gold_status"] == "SCORABLE"
                and (args.set / "cases" / r["case_id"] / r["input"]).exists()
                and (not args.only or r["case_id"] in args.only)]
        client = AsyncAnthropic(api_key=get_settings().anthropic_api_key, max_retries=3)
        spend = Spend(args.set / "spend.jsonl", args.run, args.max_usd)
        sem = asyncio.Semaphore(CONCURRENCY)
        meter = metering(spend) if args.product else contextlib.nullcontext()
        with meter:
            results = await asyncio.gather(*(run_case(client, sem, spend, args.set / "cases" / c, out_dir,
                                                      args.product) for c in todo),
                                           return_exceptions=True)
        failed = [(c, r) for c, r in zip(todo, results) if isinstance(r, BaseException)]
        for c, r in failed:
            print(f"실패 {c}: {r}")
        print(f"이번 실행 비용 추정 ${spend.total:.2f}, 사례 {len(todo)}건 중 실패 {len(failed)}건")
    rep = report(args.set, out_dir)
    for key, g in rep["groups"].items():
        if not key.startswith("case:"):
            print(f"{key:28} {g['mentioned']:>4}/{g['total']:<4} 추출률 {g['recall']:.1%}  필수 {g['must_recall'] or 0:.1%}"
                  f"  값 다름 {g['value_differs']}")


if __name__ == "__main__":
    asyncio.run(main())
