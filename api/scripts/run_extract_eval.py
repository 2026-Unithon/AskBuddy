"""13.2 추출 평가 — 자료를 파이프라인에 태우고 사실 정답지와 대조한다.

  python scripts/run_extract_eval.py --store store-a --label E-O0-baseline
  python scripts/run_extract_eval.py --store store-a --label rerun --reuse-cards
  python scripts/run_extract_eval.py --store store-c --label sealed-BASE-1 \
    --allow-holdout --campaign /git-excluded/campaign.json \
    --campaign-candidate BASE --campaign-repeat 1

측정하는 것: E-O0 추출 손실 = 원본에 있는데 카드에 없는 비율.
**시스템 정확도의 천장이다.** 여기서 흘린 것은 검색을 고쳐도 복구되지 않는다.

holdout 매장은 `--allow-holdout` 없이는 돌지 않는다. 한 번 열면 되돌릴 수 없다.
"""
from __future__ import annotations

import argparse
import pathlib
import asyncio
import json
import logging
import mimetypes
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

# 파이프라인 내부 로그를 보이게 한다. logging.basicConfig 는 app/main.py 에만 있어서
# 스크립트로 돌리면 구간 분할·조립이 실제로 돌았는지 확인할 수가 없었다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
from app.deps import get_pool, init_pool, close_pool  # noqa: E402
from app.ingest import repository as ingest_repo  # noqa: E402
from app.ingest.pipeline import process_source  # noqa: E402
from app.ingest.preprocess import storage  # noqa: E402
from app.team.extraction import (  # noqa: E402
    ExtractionReport, aggregate, judge_run_health, match_fact,
    match_fact_in_ledger, score_output, variant_axis, applicability, SCORER_VERSION, score_expected_fact,
)
from app.team.snapshot import code_version, prompt_digest  # noqa: E402
from app.team.eval_campaign import (  # noqa: E402
    CampaignError, append_campaign_event, claim_campaign_run, enforce_observed_budget,
    sha256_bytes, sha256_file, validate_campaign,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "eval" / "data"
# manifest 의 authority 를 SCAN 문서 분류로 옮긴다
_DOC_CATEGORY = {"RECIPE_BOOK": "RECIPE", "NOTICE": "MANUAL", "OWNER_ANSWER": "ETC", "OTHER": "ETC"}
REPORT_DIR = Path(__file__).resolve().parents[1] / "eval" / "reports"


# ── 자료 적재 ──────────────────────────────────────────────────────────────

def _duration_sec(path: Path) -> int:
    """ffprobe 로 길이를 잰다. 없거나 실패하면 0 — 파이프라인은 길이를 강제하지 않는다."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        return int(float(out))
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0


def _page_count(path: Path) -> int:
    """PDF 쪽수. 이미지면 1장이다."""
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        data = path.read_bytes()
        return max(1, data.count(b"/Type /Page") - data.count(b"/Type /Pages")) or 1
    except OSError:
        return 1


async def _create_child_row(
    conn: asyncpg.Connection, source_id: int, source_type: str, path: Path,
    doc_category: str | None = None,
) -> None:
    """유형별 자식 행. 파이프라인이 이 행을 전제로 전처리한다.

    제품 경로에서는 POST /ingest/sources 가 만든다. 평가 스크립트도 같은 계약을 지킨다.
    """
    # video·voice 의 포맷은 소문자, scan 의 doc_type 은 대문자다 (DB check 제약)
    ext = path.suffix.lstrip(".").lower()
    if source_type == "VIDEO":
        await ingest_repo.create_video(
            conn, source_id,
            video_format=ext, duration_sec=_duration_sec(path),
            resolution=None, fps=None,
        )
    elif source_type == "VOICE":
        await ingest_repo.create_voice(
            conn, source_id,
            audio_format=ext, duration_sec=_duration_sec(path),
            record_method="UPLOAD", sample_rate=None,
        )
    elif source_type == "KAKAO":
        await ingest_repo.create_kakao(
            conn, source_id, import_type="TXT_EXPORT", room_name=None,
        )
    elif source_type == "SCAN":
        doc_type = {"pdf": "PDF", "png": "PNG"}.get(ext, "JPG")
        await ingest_repo.create_scan(
            conn, source_id,
            doc_type=doc_type, doc_category=doc_category, page_count=_page_count(path),
        )
    else:
        raise ValueError(f"알 수 없는 source_type: {source_type}")

async def ingest_sources(
    conn: asyncpg.Connection,
    store_id: int,
    store_dir: Path,
    manifest: dict[str, Any],
    uploaded_by: int,
    only_types: set[str] | None = None,
    only_keys: set[str] | None = None,
) -> dict[int, str]:
    """manifest 의 파일을 Storage 에 올리고 sources 행을 만든 뒤 파이프라인을 돌린다.

    source_id → source_key 매핑을 돌려준다. 어느 자료에서 나온 카드인지 되짚기 위함이다.

    `only_types` 를 주면 그 유형만 올린다. 한 축(예: PDF 입력 방식)만 비교할 때
    영상 STT 까지 매 반복 다시 돌리면 비용이 수십 배로 늘고, 비교와 무관한
    변동이 결과에 섞인다. **분모도 그 유형으로 좁혀서 보고해야 한다.**
    """
    mapping: dict[int, str] = {}
    for entry in manifest["sources"]:
        if only_types and entry["type"] not in only_types:
            continue
        if only_keys and entry["source_key"] not in only_keys:
            continue
        path = store_dir / entry["file"]
        data = path.read_bytes()
        object_path = storage.build_object_path(store_id, entry["type"], path.name)
        file_url = await storage.upload(
            object_path,
            data,
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        source_id = await ingest_repo.create_source(
            conn, store_id,
            uploaded_by=uploaded_by,
            source_type=entry["type"],
            file_url=file_url,
            title=entry["source_key"],
            file_size=len(data),
            content_hash=storage.sha256_of(path),
            mime_type=mimetypes.guess_type(path.name)[0],
            original_filename=path.name,
        )
        await _create_child_row(
            conn, int(source_id), entry["type"], path,
            doc_category=_DOC_CATEGORY.get(entry.get("authority", ""), "ETC"),
        )
        mapping[int(source_id)] = entry["source_key"]
        print(f"    올림 {entry['source_key']:<24} {entry['type']:<6} {len(data)/1024:,.0f}KB")
    return mapping


async def run_pipeline(store_id: int, source_ids: list[int],
                       extraction_run_id: int | None = None) -> None:
    for i, source_id in enumerate(source_ids, 1):
        print(f"    처리 {i}/{len(source_ids)} source_id={source_id} ...", flush=True)
        # 평가 실행의 호출은 고객 월 비용이 아니다 (EVALUATION).
        # 합산하면 D21 이 거짓으로 실패한다
        await process_source(store_id, source_id,
                             cost_phase="REGISTRATION", cost_purpose="EVALUATION",
                             extraction_run_id=extraction_run_id)


# ── 채점 ──────────────────────────────────────────────────────────────────

async def fetch_cards(conn: asyncpg.Connection, store_id: int) -> list[dict[str, Any]]:
    """이 매장의 추출 카드 전부. 승인 여부와 무관하다 —
    추출 품질은 점주 검수 전 단계의 문제다."""
    rows = await conn.fetch(
        """
        select c.card_id, c.title, c.content, c.source_id
        from knowledge_cards c
        where c.store_id = $1
        order by c.card_id
        """,
        store_id,
    )
    return [dict(r) for r in rows]


async def fetch_ledger(conn: asyncpg.Connection, store_id: int) -> list[dict[str, Any]]:
    """이 매장의 사실 원장. 추출이 무엇을 뽑았는지 그대로 담고 있다."""
    rows = await conn.fetch(
        """
        select fact_id, subject, variant, attribute, value, source_id
        from source_facts
        where store_id = $1
        order by fact_id
        """,
        store_id,
    )
    return [dict(r) for r in rows]


def score(
    facts: list[dict], cards: list[dict], source_types: dict[str, str],
    ledger: list[dict] | None = None,
) -> ExtractionReport:
    """정답지를 두 번 대조한다.

    ① 원장 — 추출이 이 사실을 뽑았는가
    ② 카드 — 그 사실이 카드에 실렸는가

    둘을 갈라야 손실이 map 에서 났는지 조립에서 났는지 알 수 있다.
    """
    ledger = ledger or []
    report = ExtractionReport()
    # 규격 축과 별개로 얼음 레시피의 ICE 표시는 필수다.
    axis = variant_axis(facts)
    for fact in facts:
        stype = source_types.get(fact.get("source_key", ""), "UNKNOWN")
        in_ledger, ledger_fact_id = match_fact_in_ledger(fact, ledger)
        from app.team.extraction import normalize
        needs_variant = axis.get(normalize(fact.get("subject") or ""), False)
        fact = {**fact, "applicability": applicability(fact, needs_variant)}
        report.add(
            fact, score_expected_fact(fact, cards, facts, require_variant=needs_variant), stype,
            in_ledger=in_ledger, ledger_fact_id=ledger_fact_id,
        )
    return report


# ── 리포트 ────────────────────────────────────────────────────────────────

def write_report(run_id: int, slug: str, label: str, metrics: dict, rows: list[dict],
                 truth_confidence: str, snapshot: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = REPORT_DIR / f"extract{run_id:05d}_{slug}_{stamp}"

    base.with_suffix(".json").write_text(
        json.dumps({"run_id": run_id, "store": slug, "label": label,
                    "truth_confidence": truth_confidence, "settings": snapshot,
                    "metrics": metrics, "results": rows,
                    "scorer_version": SCORER_VERSION,
                    "inputs": _PARTIAL.get("score_inputs")},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    L = [
        f"# 추출 평가 {run_id} — {slug} · {label}",
        "",
        f"- 코드 `{snapshot['code_version']}` · 프롬프트 `{snapshot['prompt_version']}`",
        f"- 모델 `{snapshot['extract_model']}` · ingest_mode `{snapshot['ingest_mode']}`"
        f" · temp `{snapshot['extract_temperature']}`",
        f"- 구간 {snapshot['video_segment_sec'] or '분할없음'}초 · "
        f"흐름 {snapshot['pipeline_version']}",
        f"- 영상 `{snapshot['video_input_mode']}` · 프레임 상한 "
        f"`{snapshot['video_max_frames_to_model'] or '없음'}`"
        f" · 간격 {snapshot['frame_interval_sec']}초",
        f"- 사실 {metrics['fact_count']}건 · 생성 카드 {metrics['card_count']}장",
        "",
    ]
    if truth_confidence == "TEST":
        L += [
            "> **정답지는 팀 자체 판정(`TEST`)이다. 점주 확인이 아니다.**",
            "> 아래 수치는 '우리가 정답이라고 본 것 대비' 이지 '매장 사실 대비' 가 아니다.",
            "",
        ]
    L += [
        "## E-O0 추출 손실",
        "",
        "| | 값 |",
        "|---|---:|",
        f"| **손실 (E-O0)** | **{metrics['loss'] * 100:.1f}%** |",
        f"| 재현율 | {metrics['recall'] * 100:.1f}% |",
        f"| 담김 / 부분 / 누락 | {metrics['covered']} / {metrics['partial']} / {metrics['missing']} |",
        "",
        "**이것이 시스템 정확도의 천장이다.** 여기서 흘린 사실은 검색·생성을 아무리 고쳐도 복구되지 않는다.",
        "",
        "## 출력 주장 정확도",
        "",
        "정답지는 전수가 아니다. '정답지에 없다' 를 '틀렸다' 로 세지 않고",
        "판정불가로 남겨 표본 판정으로 넘긴다.",
        "",
        (lambda o: (f"- 뽑은 주장 {o['claim_count']}건 — 일치 {o['MATCHED']} · "
                    f"오연결 {o['CONFLICT']} · 판정불가 {o['UNVERIFIED']}\n"
                    f"- 정확도 {o['precision_lower'] * 100:.1f}~"
                    f"{o['precision_upper'] * 100:.1f}%")
         if o.get("claim_count") else "- 출력 주장 없음")(metrics.get("output") or {}),
        "",
        "## 치명 누락 (must_have)",
        "",
    ]
    mh = metrics["must_have"]
    L += [
        f"- 필수 사실 {mh['fact_count']}건 중 **{mh['fact_count'] - mh['covered']}건 누락** "
        f"(손실 {mh['loss'] * 100:.1f}%)",
        "",
    ]
    if metrics["must_have_missing_ids"]:
        L += ["누락된 필수 사실:", ""]
        by_id = {r["fact_id"]: r for r in rows}
        for fid in metrics["must_have_missing_ids"][:40]:
            r = by_id.get(fid, {})
            L.append(f"- `{fid}` {r.get('subject','')} {r.get('variant') or ''} "
                     f"— {r.get('attribute','')} = {r.get('value','')} ({r.get('verdict')})")
        L.append("")

    # ── 손실이 어느 단계에서 났는가 ────────────────────────────────────
    stage = metrics.get("loss_stage") or {}
    if stage:
        n = metrics["fact_count"]
        L += [
            "## 손실 단계 — map 인가 조립인가",
            "",
            "정답지를 두 번 대조한다. ① 추출이 사실을 **뽑았는가**(원장)",
            "② 그 사실이 **카드에 실렸는가**. 둘을 갈라야 어디를 고칠지 정해진다.",
            "",
            "| 단계 | 뜻 | 건수 | 비율 |",
            "|---|---|---:|---:|",
        ]
        labels = [
            ("OK",         "뽑았고 카드에도 실렸다"),
            ("ASSEMBLY",   "**뽑았는데 카드에 안 실렸다** — 조립이 문제"),
            ("CARD_ONLY",  "카드 본문엔 있으나 사실로는 안 뽑혔다"),
            ("EXTRACTION", "**아예 못 뽑았다** — map 이 문제"),
        ]
        for key, desc in labels:
            c = stage.get(key, 0)
            L.append(f"| `{key}` | {desc} | {c} | {c / n * 100:.1f}% |")
        L += [
            "",
            f"원장 재현율 {metrics.get('ledger_recall', 0) * 100:.1f}% "
            f"— 정답지 사실 중 추출이 실제로 뽑아낸 비율이다.",
            "",
        ]
        by_stype = metrics.get("loss_stage_by_source_type") or {}
        if by_stype:
            L += ["| 유형 | OK | ASSEMBLY | CARD_ONLY | EXTRACTION |",
                  "|---|---:|---:|---:|---:|"]
            for stype, counts in by_stype.items():
                L.append(
                    f"| {stype} | {counts.get('OK', 0)} | {counts.get('ASSEMBLY', 0)} "
                    f"| {counts.get('CARD_ONLY', 0)} | {counts.get('EXTRACTION', 0)} |"
                )
            L += [
                "",
                "`EXTRACTION` 이 크면 뽑기(map)를, `ASSEMBLY` 가 크면 조립(reduce)을 고친다.",
                "",
            ]

    L += ["## source type 별", "", "| 유형 | 사실 | 담김 | 부분 | 누락 | 손실 |", "|---|---:|---:|---:|---:|---:|"]
    for stype, b in metrics["by_source_type"].items():
        L.append(f"| {stype} | {b['fact_count']} | {b['covered']} | {b['partial']} "
                 f"| {b['missing']} | {b['loss'] * 100:.1f}% |")
    L += ["", "손실이 큰 유형부터 고친다 (13.4).", ""]

    if metrics["partial_reasons"]:
        L += ["## 부분 포착 사유", ""]
        for reason, n in metrics["partial_reasons"].items():
            L.append(f"- {reason} — {n}건")
        L.append("")

    L += ["## 전체 사실", "", "| fact | 대상 | 규격 | 속성 | 판정 | 카드 |", "|---|---|---|---|---|---:|"]
    for r in rows:
        L.append(f"| `{r['fact_id']}` | {r['subject']} | {r['variant'] or '-'} "
                 f"| {r['attribute']} | {r['verdict']} | {r['card_id'] or '-'} |")
    base.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return base.with_suffix(".md")


# ── 실행 ──────────────────────────────────────────────────────────────────

def _drifted_sources(store_dir: pathlib.Path, manifest: dict) -> list[str]:
    """기록된 해시와 지금 파일이 다른 자료를 찾는다.

    영상을 다시 인코딩하거나 스캔을 다시 찍으면 입력이 조용히 달라진다. 그걸
    모르고 재면 입력이 바뀐 결과를 개선으로 읽는다 — 프레임 실험에서 겪은 일이다.
    """
    drifted = []
    for source in manifest["sources"]:
        recorded = source.get("sha256")
        target = store_dir / source["file"]
        if not recorded or not target.exists():
            continue
        digest = hashlib.sha256()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != recorded:
            drifted.append(source["source_key"])
    return drifted


def _campaign_settings(s: Any, args: argparse.Namespace) -> dict[str, Any]:
    """후보가 바뀌면 결과도 바뀌는 값만 비밀 없이 고정한다."""
    return {
        "scorer_version": SCORER_VERSION,
        "code_version": code_version(),
        "extract_prompt_version": prompt_digest("extract_facts.ko.txt"),
        "assemble_prompt_version": prompt_digest("assemble_cards.ko.txt"),
        "extraction_schema_hash": sha256_file(
            Path(__file__).resolve().parents[1] / "app" / "ingest" / "schemas.py"
        ),
        "extract_model": s.gemini_model,
        "stt_model": s.stt_model,
        "embedding_model": s.embedding_model,
        "ingest_mode": s.ingest_mode,
        "extract_temperature": s.extract_temperature,
        "video_input_mode": s.video_input_mode,
        "video_max_frames_to_model": s.video_max_frames_to_model,
        "frame_interval_sec": s.frame_interval_sec,
        "video_segment_sec": s.video_segment_sec,
        "pipeline_version": "facts_then_cards/v1",
        "reuse_cards": bool(args.reuse_cards),
        "reuse_sources": bool(args.reuse_sources),
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description="추출 평가 (E-O0)")
    ap.add_argument("--store", help="예: store-a")
    ap.add_argument("--label")
    ap.add_argument("--allow-holdout", action="store_true",
                    help="holdout 매장을 연다. 한 번 열면 되돌릴 수 없다")
    ap.add_argument("--reuse-cards", action="store_true",
                    help="자료를 다시 넣지 않고 기존 카드로 채점만 한다")
    ap.add_argument("--reuse-sources", action="store_true",
                    help="이미 올린 자료를 다시 태운다. 업로드와 STT 를 건너뛰므로 "
                         "추출 변동만 분리해서 잴 수 있다")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--only-source", default=None,
                    help="쉼표로 구분한 source_key 만 처리한다. 자료 하나로 축을 "
                         "빠르게 떠볼 때 쓴다. 반복 1회는 방향 탐색이지 판정이 아니다")
    ap.add_argument("--only-type", default=None,
                    help="쉼표로 구분한 source_type 만 처리한다 (예: SCAN). "
                         "한 축만 비교할 때 쓴다. 분모도 함께 좁혀 보고한다")
    ap.add_argument("--campaign", default=None,
                    help="사전등록 캠페인 JSON. holdout 을 열 때는 필수다")
    ap.add_argument("--campaign-candidate", default=None,
                    help="캠페인에 등록한 후보 이름")
    ap.add_argument("--campaign-repeat", type=int, default=None,
                    help="후보의 사전등록 반복 번호")
    ap.add_argument("--print-campaign-settings", action="store_true",
                    help="현재 후보 settings JSON을 출력하고 종료한다")
    args = ap.parse_args()
    _PARTIAL.clear()

    if args.print_campaign_settings:
        print(json.dumps(_campaign_settings(get_settings(), args), ensure_ascii=False,
                         indent=2, sort_keys=True))
        return 0
    if not args.store or not args.label:
        ap.error("--store와 --label이 필요하다")

    store_dir = DATA_DIR / args.store
    manifest_path = store_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    slug = manifest["store_slug"]

    # ── holdout guard ────────────────────────────────────────────────────
    # **정답지를 읽기 전에** 판단한다. 읽고 나서 막으면 이미 이 프로세스가
    # 정답을 손에 쥔 뒤다 — 로그·예외·디버거 어디로든 샐 수 있다.
    if manifest.get("split") == "holdout" and not args.allow_holdout:
        print(f"{args.store} 는 holdout 이다. 개선 중에 열면 holdout 이 아니게 된다.\n"
              f"정말 열려면 --allow-holdout 을 붙이고, SPLIT.md 의 개봉 기록에 남긴다.",
              file=sys.stderr)
        return 2
    if manifest.get("split") == "holdout" and not args.campaign:
        # 열기로 했다면 무엇을 검증하려는지 먼저 적어야 한다. 열어 보고 나서
        # 가설을 정하면 holdout 이 아니라 두 번째 dev 가 된다 (D17)
        print("holdout 은 사전등록한 캠페인에서만 연다. --campaign <파일> 을 붙인다.",
              file=sys.stderr)
        return 2

    campaign = None
    campaign_run = None
    campaign_path = None
    campaign_claimed = False
    if args.campaign:
        campaign_path = pathlib.Path(args.campaign)
        try:
            campaign_bytes = campaign_path.read_bytes()
            campaign = json.loads(campaign_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"캠페인 파일을 읽을 수 없다: {exc}", file=sys.stderr)
            return 2
        if not args.campaign_candidate or args.campaign_repeat is None:
            print("캠페인 실행에는 --campaign-candidate와 --campaign-repeat가 필요하다.",
                  file=sys.stderr)
            return 2

    # dev는 즉시 확인한다. holdout 캠페인은 원본을 읽기 전에 먼저 권한/slot을 잠근다.
    if campaign is None:
        drifted = _drifted_sources(store_dir, manifest)
        if drifted:
            print(f"자료가 기록된 해시와 다르다: {', '.join(drifted)}\n"
                  f"기준선과 같은 입력이 아니다. scripts/backfill_source_hashes.py --check 로 확인한다.",
                  file=sys.stderr)
            return 2

    s = get_settings()
    if campaign is not None:
        try:
            recorded_source_hashes = {}
            for entry in manifest["sources"]:
                digest = str(entry.get("sha256") or "")
                recorded_source_hashes[entry["source_key"]] = (
                    digest if digest.startswith("sha256:") else "sha256:" + digest
                )
            campaign_run = validate_campaign(
                campaign,
                campaign_bytes=campaign_bytes,
                store=args.store,
                split=str(manifest.get("split") or ""),
                manifest_hash=sha256_bytes(manifest_bytes),
                source_hashes=recorded_source_hashes,
                source_bytes=None,
                runtime_settings=_campaign_settings(s, args),
                candidate=args.campaign_candidate,
                repeat=args.campaign_repeat,
                label=args.label,
            )
            claim_campaign_run(campaign_path, campaign_run)
            campaign_claimed = True
            # 여기서부터가 실제 개봉이다. 실패도 같은 slot의 시도로 남긴다.
            source_paths = {entry["source_key"]: store_dir / entry["file"]
                            for entry in manifest["sources"]}
            missing = [key for key, path in source_paths.items() if not path.is_file()]
            if missing:
                raise CampaignError(f"원본 파일이 없다: {', '.join(missing)}")
            actual_hashes = {key: sha256_file(path) for key, path in source_paths.items()}
            if actual_hashes != campaign_run.source_hashes:
                raise CampaignError("실제 원본 hash가 사전등록 값과 다르다")
            source_bytes = sum(path.stat().st_size for path in source_paths.values())
            if source_bytes > campaign_run.max_source_bytes:
                raise CampaignError("입력 원본 크기가 실행당 byte 예산을 넘는다")
        except (CampaignError, OSError, json.JSONDecodeError) as exc:
            if campaign_claimed and campaign_run is not None and campaign_path is not None:
                append_campaign_event(campaign_path, campaign_run, "FAILED", detail=str(exc),
                                      ai_attempt_count=0, cost_usd="0")
            print(f"캠페인 사전 검증 실패: {exc}", file=sys.stderr)
            return 2

    # holdout 정답은 캠페인 검증과 slot 잠금이 끝난 뒤에만 처음 읽는다.
    truth_path = store_dir / "truth" / "facts.json"
    try:
        truth_bytes = truth_path.read_bytes()
    except OSError as exc:
        if campaign_run is not None:
            append_campaign_event(campaign_path, campaign_run, "FAILED", detail=str(exc),
                                  ai_attempt_count=0, cost_usd="0")
        print(f"정답지 파일을 읽을 수 없다: {exc}", file=sys.stderr)
        return 2
    if campaign_run is not None:
        if sha256_bytes(truth_bytes) != campaign_run.truth_hash:
            append_campaign_event(campaign_path, campaign_run, "FAILED",
                                  detail="truth hash mismatch",
                                  ai_attempt_count=0, cost_usd="0")
            print("캠페인 사전 검증 실패: truth hash가 등록값과 다르다", file=sys.stderr)
            return 2
        append_campaign_event(campaign_path, campaign_run, "OPENED")
    try:
        truth = json.loads(truth_bytes)
    except json.JSONDecodeError as exc:
        if campaign_run is not None:
            append_campaign_event(campaign_path, campaign_run, "FAILED", detail=str(exc),
                                  ai_attempt_count=0, cost_usd="0")
        print(f"정답지 JSON이 잘못됐다: {exc}", file=sys.stderr)
        return 2
    args.campaign_run = campaign_run
    confirmed = truth.get("owner_confirmed")
    truth_confidence = "OWNER" if confirmed is True else "TEST"

    # 스윕하는 값은 반드시 여기 남아야 한다. 없으면 결과를 설정에 귀속시킬 수 없다
    snapshot = {
        "scorer_version": SCORER_VERSION,
        "truth_hash": "sha256:" + hashlib.sha256(json.dumps(truth, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "code_version": code_version(),
        "prompt_version": prompt_digest("extract_facts.ko.txt"),
        "assemble_prompt_version": prompt_digest("assemble_cards.ko.txt"),
        "extract_model": s.gemini_model,
        "stt_model": s.stt_model,
        "ingest_mode": s.ingest_mode,
        "embedding_model": s.embedding_model,
        "extract_temperature": s.extract_temperature,
        "video_input_mode": s.video_input_mode,
        "video_max_frames_to_model": s.video_max_frames_to_model,
        "frame_interval_sec": s.frame_interval_sec,
        "video_segment_sec": s.video_segment_sec,
        "pipeline_version": "facts_then_cards/v1",
        # 무엇을 검증하려고 돌렸는가. holdout 개봉은 이 기록 없이는 근거가 없다
        "campaign": ({"campaign_id": campaign_run.campaign_id,
                      "campaign_hash": campaign_run.campaign_hash,
                      "slot": campaign_run.slot,
                      "candidate": campaign_run.candidate,
                      "repeat": campaign_run.repeat}
                     if campaign_run else None),
        # 입력 자료의 지문. 같은 자료로 잰 것인지 나중에 대조한다
        "source_hashes": {x["source_key"]: (x.get("sha256") or "")[:16]
                          for x in manifest["sources"]},
    }

    await init_pool()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            store_id = await conn.fetchval(
                "select store_id from stores where store_slug = $1", slug)
            if store_id is None:
                print(f"매장이 없다: {slug}. seed_eval_stores.py 를 먼저 돌린다", file=sys.stderr)
                return 1
            owner = await conn.fetchval(
                "select user_id from users order by user_id limit 1")

            run_id = int(await conn.fetchval(
                """
                insert into extraction_runs (
                  store_id, label, code_version, prompt_version, extract_model,
                  stt_model, ingest_mode, settings, truth_confidence,
                  source_count, fact_count, notes, created_by
                )
                values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13)
                returning run_id
                """,
                store_id, args.label, snapshot["code_version"], snapshot["prompt_version"],
                snapshot["extract_model"], snapshot["stt_model"], snapshot["ingest_mode"],
                json.dumps(snapshot, ensure_ascii=False), truth_confidence,
                len(manifest["sources"]), len(truth["facts"]), args.notes, owner,
            ))
            print(f"run_id={run_id} {slug} · {args.label} · 정답지 {truth_confidence}")
            print(f"  코드 {snapshot['code_version']} · 프롬프트 {snapshot['prompt_version']}"
                  f" · ingest_mode={snapshot['ingest_mode']}")
            if campaign_run is not None:
                append_campaign_event(campaign_path, campaign_run, "STARTED", run_id=run_id)

            source_types: dict[str, str] = {
                e["source_key"]: e["type"] for e in manifest["sources"]}

            # 도중에 죽어도 실행을 RUNNING 으로 방치하지 않는다.
            # RUNNING 인 실행은 동결 트리거가 풀려 있어 나중에 덮어써질 수 있다
            try:
                await _execute(conn, run_id, store_id, store_dir, manifest,
                               truth, source_types, owner, args)
            except Exception:
                await conn.execute(
                    "update extraction_runs set status='FAILED', finished_at=now() "
                    "where run_id=$1 and status='RUNNING'",
                    run_id,
                )
                if campaign_run is not None:
                    usage = _PARTIAL.get("campaign_usage") or {}
                    append_campaign_event(campaign_path, campaign_run, "FAILED", run_id=run_id,
                                          detail="evaluation failed",
                                          ai_attempt_count=usage.get("ai_attempt_count"),
                                          cost_usd=usage.get("cost_usd"))
                raise

            row = await conn.fetchrow(
                "select metrics, card_count from extraction_runs where run_id=$1", run_id)
            metrics = row["metrics"] if isinstance(row["metrics"], dict) else json.loads(row["metrics"])
            cards_n = int(row["card_count"])
            report_rows = [dict(r) for r in await conn.fetch(
                """select fact_id, subject, variant, attribute, value, must_have,
                          source_key, source_type, verdict, card_id, score, reason
                   from extraction_results where run_id=$1 order by fact_id""", run_id)]

    finally:
        await close_pool()

    path = write_report(run_id, slug, args.label, metrics, report_rows,
                        truth_confidence, snapshot)
    if campaign_run is not None:
        usage = _PARTIAL.get("campaign_usage") or {}
        append_campaign_event(campaign_path, campaign_run, "SUCCEEDED", run_id=run_id,
                              ai_attempt_count=usage.get("ai_attempt_count"),
                              cost_usd=usage.get("cost_usd"))
    mh = metrics["must_have"]
    print(f"\n  E-O0 추출 손실 {metrics['loss'] * 100:.1f}% "
          f"(재현율 {metrics['recall'] * 100:.1f}%, 카드 {cards_n}장)")
    print(f"  치명 누락 {mh['fact_count'] - mh['covered']}/{mh['fact_count']}")
    out = metrics.get("output") or {}
    if out.get("claim_count"):
        print(f"  뽑은 주장 {out['claim_count']}건 — 정답 일치 {out['MATCHED']} · "
              f"오연결 {out['CONFLICT']} · 판정불가 {out['UNVERIFIED']}")
        print(f"  정확도 {out['precision_lower'] * 100:.1f}~"
              f"{out['precision_upper'] * 100:.1f}% "
              f"(판정불가를 전부 오답/정답으로 봤을 때의 폭)")
        if out["CONFLICT"]:
            # 같은 대상에 다른 값을 실어 보내는 것이 누락보다 위험하다.
            # 신입은 그걸 읽고 그대로 따른다
            print(f"  ⚠ 오연결 {out['CONFLICT']}건 — 같은 대상 다른 값: "
                  f"{out['conflict_ids'][:8]}")
    print(f"  리포트: {path}")
    return 0


# 이 실행에서 몇 건이 실패했는가. 상태를 SUCCEEDED 로 닫을지 가른다
_PARTIAL: dict = {}


async def _execute(conn, run_id, store_id, store_dir, manifest, truth,
                   source_types, owner, args) -> None:
    """자료 적재 → 추출 → 채점 → 저장. 실패하면 호출부가 실행을 FAILED 로 닫는다."""
    if args.reuse_cards:
        print("  기존 카드로 채점만 한다 (--reuse-cards)")
    elif args.reuse_sources:
        rows = await conn.fetch(
            "select source_id from sources where store_id = $1 order by source_id",
            store_id)
        if not rows:
            raise RuntimeError("올려둔 자료가 없다. --reuse-sources 없이 먼저 한 번 돌린다")
        print(f"  기존 자료 {len(rows)}건을 다시 태운다 (업로드·STT 건너뜀)")
        await run_pipeline(store_id, [int(r["source_id"]) for r in rows], run_id)
    else:
        print("  자료 적재")
        only = ({t.strip().upper() for t in args.only_type.split(',')}
                if getattr(args, 'only_type', None) else None)
        keys = ({k.strip() for k in args.only_source.split(',')}
                if getattr(args, 'only_source', None) else None)
        mapping = await ingest_sources(conn, store_id, store_dir, manifest,
                                       owner, only_types=only, only_keys=keys)
        print("  추출 파이프라인")
        await run_pipeline(store_id, list(mapping), run_id)

    # ── 자료 처리 결과를 확인한다 ──────────────────────────────────────
    # process_source 는 예외를 안에서 삼키고 자료를 FAILED 로 표시한다. 여기서
    # 확인하지 않으면 **한 건도 못 뽑은 실행이 SUCCEEDED 로 기록된다** —
    # 그리고 빈 실행 둘을 비교해 "차이 없음" 이라는 답이 나온다. 실제로 겪었다.
    if not args.reuse_cards:
        states = await conn.fetch(
            "select status, count(*) as n from sources where store_id = $1 "
            "group by status", store_id)
        counts = {r["status"]: int(r["n"]) for r in states}
        failed = counts.get("FAILED", 0)
        if failed:
            print(f"  ⚠ 자료 {failed}/{sum(counts.values())}건 처리 실패: {counts}")
        _PARTIAL["source_states"] = counts

    # 원장에서 실행 단위 원가 summary 를 만든다 (CP-00B)
    cost = None
    try:
        from app.deps import get_pool
        from app.usage.repository import rollup_extraction_run
        cost = await rollup_extraction_run(get_pool(), store_id, run_id)
        print(f"  원가: 호출 {cost['ai_attempt_count']}회 "
              f"(재시도 {cost['retry_count']} · 미관측 {cost['unknown_attempt_count']}) "
              f"· 토큰 {cost['prompt_tokens'] or '?'}/{cost['completion_tokens'] or '?'} "
              f"· {cost['cost_status']}")
    except Exception as exc:
        print(f"  원가 집계 실패(측정은 원장에 남아 있다): {exc}")

    campaign_run = getattr(args, "campaign_run", None)
    if campaign_run is not None:
        if cost is not None and cost.get("cost_usd") is not None:
            _PARTIAL["campaign_usage"] = {
                "ai_attempt_count": cost.get("ai_attempt_count"),
                "cost_usd": str(cost.get("cost_usd")),
            }
        _PARTIAL["campaign_usage"] = enforce_observed_budget(
            campaign_run, cost, pathlib.Path(args.campaign)
        )

    cards = await fetch_cards(conn, store_id)
    ledger = await fetch_ledger(conn, store_id)
    _PARTIAL["score_inputs"] = {"cards": [dict(c) for c in cards],
                                "ledger": [dict(r) for r in ledger],
                                "truth": truth["facts"], "source_types": source_types}
    report = score(truth["facts"], cards, source_types, ledger)
    print(f"  원장 {len(ledger)}건 · 카드 {len(cards)}장")
    # 측정이 아닌 것을 측정으로 기록하지 않는다 (W0). 판정은 순수 함수에 있고
    # tests/test_run_health.py 가 그 함수를 검사한다
    health, reason = judge_run_health(_PARTIAL.get("source_states") or {}, len(cards))
    if reason:
        raise RuntimeError(f"{reason}. 로그를 보고 원인을 고친 뒤 다시 돌린다")
    _PARTIAL["health"] = health

    metrics = aggregate(report.rows, card_count=len(cards))
    # 정답지만 순회하면 재현율만 보인다. 뽑아낸 주장 쪽에서도 센다 (W0)
    output = score_output(ledger, truth["facts"])
    metrics["output"] = {k: v for k, v in output.items() if k != "rows"}

    await conn.executemany(
        """
        insert into extraction_results (
          run_id, store_id, fact_id, subject, variant, attribute, value,
          must_have, source_key, source_type, verdict, card_id, score,
          reason, subject_hit, value_hit, variant_hit,
          in_ledger, ledger_fact_id, loss_stage
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                  $18,$19,$20)
        """,
        [(run_id, store_id, r["fact_id"], r["subject"], r["variant"],
          r["attribute"], r["value"], r["must_have"], r["source_key"],
          r["source_type"], r["verdict"], r["card_id"], r["score"],
          r["reason"], r["subject_hit"], r["value_hit"], r["variant_hit"],
          r["in_ledger"], r["ledger_fact_id"], r["loss_stage"])
         for r in report.rows],
    )
    await conn.execute(
        """
        update extraction_runs
        set status=$5, finished_at=now(), metrics=$3::jsonb, card_count=$4
        where run_id=$1 and store_id=$2
        """,
        run_id, store_id, json.dumps(metrics, ensure_ascii=False), len(cards),
        # 일부 자료가 실패한 실행을 성공으로 닫지 않는다. 분모가 달라진 측정이다
        _PARTIAL.get("health", "SUCCEEDED"),
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
