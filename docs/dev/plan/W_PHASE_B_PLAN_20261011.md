# Phase B — 입구 분류기 · 정규화기 · 체크리스트 카드 단위 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업로드·점주 답변으로 들어온 자료를 본 추출 **전에** 싸게 훑어(probe) 한 번 분류하고, 구간별 로직 판정에 따라 등록된 추출기로 보낸다. NONE 은 추출하지 않고 NOTICE 는 검수 대기로 둔다. 판정은 개발용 표에 기록한다. 이와 함께 docx, 점주 선택 칩, 점주 답변 첨부, 사실 `ext`, 체크리스트 카드 단위, 분류기 평가 하네스, 다수결 참조 일반화를 만든다.

**Architecture:** 새 패키지 `api/app/ingest/intake/` 를 만든다. 하는 일은 IR·등록표 → 훑기(probe) → 분류 호출 → 결정 규칙(순수 함수) → 추출 계획(순수 함수) → 기록 순서다. `pipeline.process_source` 는 전처리 앞에서 `route_source` 를 한 번 부르고, 그 결과로 전처리 결과(글·구간)를 거른다. 이미 판정 기록이 있으면 다시 분류하지 않는다(재시도·첨부 공용). 점주 답변 worker 는 답변 글과 첨부를 한 묶음으로 분류 1회 하고, 첨부는 **보통 업로드 작업(ingest job)** 으로 넘긴다. 그 작업은 이미 저장된 판정을 재사용한다.

**Tech Stack:** FastAPI·asyncpg·pydantic v2, Gemini(`providers.measured_generate`), ffmpeg, pypdf·pypdfium2·pillow, 표준 라이브러리 zipfile·xml.etree(docx), Next.js 16 + TanStack Query(web), Playwright 합성 API(화면 확인).

**Spec:** `docs/dev/plan/W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md` (시작 문서 `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md`)

---

## 계획 단계 결정 (2026-10-11 사용자 확인 · 코드 확인)

| # | 결정 | 근거 |
|---|---|---|
| P1 | **avi·hwp(hwpx 포함)는 이번에 하지 않는다.** 새 확장자는 docx 하나 | 사용자 확정 2026-10-11 |
| P2 | 섞인 자료는 **글 자료만 구간별로 추출**한다(DOC_TEXT·CHAT·OWNER_TEXT). 영상·음성·이미지 문서는 분류만 구간별로 기록하고, 추출은 자료 전체를 1위 로직 하나로 한다 | 사용자 확정 2026-10-11. 등록 추출기가 RECIPE 하나뿐이라 지금은 결과 차이가 NONE·NOTICE 제외뿐이다. Phase D 에서 넓힌다 |
| P3 | 음성·영상 훑기 STT 는 본 추출 전체 STT 에 **재사용하지 않는다**. 다운로드·pdf 글자 층·docx·카톡 파싱은 재사용한다 | 사용자 확정. 설계 B-D3 원가 추정(훑기 STT 약 1분 추가)과 같다 |
| P4 | 체크 키는 판 단위 그대로다. 같은 영업일에 재공개되면 체크가 풀린다 | 사용자 확정(유지) |
| P5 | 점주 답변 화면 첨부 UI 는 W 가 직접 고친다(`answer-question-sheet.tsx`) | 사용자 확정 |
| P6 | 원장 단계 이름은 설계의 `ROUTE` 대신 **`CLASSIFY`** 를 쓴다 | `contracts/usage.py` `UsageStage` 와 `ai_usage_attempts.stage` check 에 `ROUTE` 가 없고 `CLASSIFY` 가 있다. contracts 는 바꾸지 않는다 |
| P7 | 분류 출력은 `range` 대신 코드가 만든 **`candidate_id`** 로 구간을 가리킨다. 위치는 서버가 후보에서 붙인다 | 모델이 범위를 다시 쓰면 경계가 어긋난다(설계 B-D3b-1 "경계는 코드가") |
| P8 | 점주 답변 첨부는 **보통 업로드 작업(ingest job)** 으로 처리한다. 답변 글 결과(PUBLISHED/REVIEW/LINKED)는 지금과 같고, 첨부에서 나온 카드는 업로드 검수 흐름을 탄다. 답변 처리 뒤에 붙은 첨부(보충)는 붙이는 순간 작업을 만든다 | 작업 상태·재시도·PARTIAL 화면을 그대로 쓴다. R 계약은 바뀌지 않는다 |
| P9 | 분류 원래 응답은 `extraction_raw_responses` 가 아니라 `intake_route_decisions.model_sections` 에 남긴다 | 그 표의 stage check 가 `EXTRACT`·`ASSEMBLE` 뿐이다. 바꾸지 않는다 |
| P10 | 사실 `ext` 는 `source_facts.ext` 에만 둔다(사실 판·hash·공개 계약 밖). 이번에는 저장 경로만 만들고 채우는 추출기는 Phase D 에 생긴다 | 설계 4-3 |
| P11 | 관찰 템플릿(B-D8 1~3)은 Phase 0 에서 이미 만들었다(`docs/dev/templates/extraction_observation/`, `build_observation_instruction.py`). 이번에는 **다수결 참조 일반화(B-D8-4)만** 한다 | 저장소 확인 |

## Global Constraints

- 저장소 `CLAUDE.md` 가 우선한다. 주석·프롬프트·문서는 한국어로 쓴다.
- **커밋·푸시를 하지 않고, 할지 묻지도 않는다.** Task 끝의 "변경 확인"은 `git status --short` 로 범위만 본다(사용자 규칙).
- 매장 격리: 모든 DB 함수는 `store_id` 를 필수 인자로 받는다. `WHERE store_id = …` 없는 조회는 쓰지 않는다. store_id 는 JWT·worker 신뢰 범위에서 온다. `api/app/` 이나 `supabase/migrations/` 를 건드린 Task 는 `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/checklist` 결과 **새 위반 0** 이어야 한다(`repository.py` 기존 15건 제외).
- R 소유 파일은 수정하지 않는다: `api/app/reg/*`, `api/app/learn/router.py`, `answering.py`, `answer_storage.py`, `owner_handoff.py`, `owner_publication.py`, `owner_delivery.py`, `approved_renderer.py`, `v2_router.py`, `knowledge_loop.py`, auth·notifications. `api/app/contracts/*` 도 바꾸지 않는다.
- 공통 파일(`api/app/config.py`, `api/app/main.py`, `api/scripts/verify_r_schema_rebuild.py`)은 가산 변경만 한다.
- migration 은 가산형이다. 적용된 파일은 고치지 않는다. 이름은 `supabase/migrations/YYYYMMDDHHMMSS_w_<주제>.sql` 이다. check 제약을 넓힐 때는 `drop constraint if exists` 다음에 `add constraint` 를 쓴다(`20261009090000_w_card_fact_edit.sql` 과 같은 방식).
- 모델명·임계값·상한은 `config.py` 에, 프롬프트는 `api/prompts/` 에 둔다. LLM 호출마다 원장(`ai_usage_attempts`)에 남기고, 모델 호출 중에는 DB 연결을 쥐지 않는다.
- `INGEST_MODE` 기본값은 mock 이다. **유료 호출(실모델 분류·STT)은 사용자 승인 없이 하지 않는다.** 검증은 합성 대역으로 한다.
- 평가용 실제 자료의 브랜드·상호·메뉴 고유명은 코드·테스트·문서·커밋 메시지에 쓰지 않는다. 합성 픽스처는 `음료Z`·`합성매장` 같은 이름을 쓴다.
- 분류 실패(모델 오류·JSON 깨짐·후보 누락)는 조용히 다른 로직으로 보내지 않는다. 자료는 FAILED 가 되고 재시도할 수 있다.
- 기존 `extract_facts.ko.txt`·응답 스키마는 바꾸지 않는다(D16 재사용 키·요청 바이트 동일).
- web: 단위 테스트 러너가 없다. "테스트 통과"라고 쓰지 않는다. `pnpm check` 와 Playwright 합성 API 확인을 나눠서 보고한다. web 에 Supabase 클라이언트·LLM 키를 두지 않는다.
- 로직 이름: `RECIPE`·`PROCEDURE`·`POLICY`·`REFERENCE`·`NOTICE`·`NONE`. 정규화기 이름: `DOC_TEXT`·`DOC_IMAGE`·`AUDIO`·`VIDEO`·`CHAT`·`OWNER_TEXT`.
- API 테스트 명령: `cd api && .venv/bin/python -m pytest -q <경로>`.

## Review Focus

1. **NONE 으로 판정된 자료.** 본 추출·전체 STT·프레임 업로드를 하지 않는다. 작업은 `NO_RESULT` 이고 메시지는 "업무 자료가 아니라고 판단해 추출하지 않았어요."다. Task 9 테스트로 고정한다.
2. **재시도·PARTIAL 재시도·복구에서 분류를 다시 부르지 않는다.** 같은 자료의 최신 판정을 재사용하므로 구간 구성(`seg1..N`)이 지난 실행과 같다. Task 9 테스트로 고정한다.
3. **NOTICE 사실이 카드에 섞이지 않는다.** 공개 카드 대상(REDRAFT)과 겹치는 경우도 마찬가지다. NOTICE 구간의 사실은 `INTAKE_NOTICE` 검수 대기로 남고, 재조립·재초안에 들어가지 않는다. Task 9 테스트(REDRAFT 대상 포함)로 고정한다.
4. **아무것도 거르지 않은 글 자료는 지금과 같은 입력이다.** 모든 구간이 같은 로직이고 NONE 이 없으면 추출 입력 글이 바이트 단위로 같아야 한다(D16). Task 8 테스트로 고정한다.
5. **답변 처리 뒤에 붙은 첨부.** 첨부 API 가 그 자리에서 작업을 만들고, 같은 첨부를 두 번 붙여도 작업은 하나다. Task 12 테스트로 고정한다.

---

## 파일 구조

| 파일 | 책임 | Task |
|---|---|---|
| `api/app/config.py` (수정) | `intake_*` 설정 | 1 |
| `api/app/ingest/capabilities.py` (수정) | SCAN 에 `docx` | 1 |
| `api/app/ingest/schemas.py` (수정) | `ScanMeta.doc_type` 에 `DOCX`, `CreateSourceRequest.owner_hints`, `ExtractedAssertion._ext` | 1·7·10 |
| `api/app/ingest/preprocess/docx.py` (신규) | docx 문단·제목·표 행 읽기 | 1 |
| `supabase/migrations/20261011090000_w_docx_doc_type.sql` (신규) | `source_scan.doc_type` 에 DOCX | 1 |
| `api/app/ingest/intake/__init__.py` (신규) | 패키지 | 2 |
| `api/app/ingest/intake/ir.py` (신규) | `Locator`·`Candidate`·`ProbeResult` | 2 |
| `api/app/ingest/intake/registry.py` (신규) | 로직·정규화기 상수, 확장자→정규화기, 로직→추출기 | 2 |
| `api/app/ingest/intake/decide.py` (신규) | 결정 규칙(가산·애매·대체·다중·상속·자료 단위) | 3 |
| `api/app/ingest/intake/grouping.py` (신규) | 글 자료 후보 묶기(쪽·docx 블록·카톡 날짜). probe·full 이 함께 쓴다 | 4 |
| `api/app/ingest/intake/probe_text.py` (신규) | DOC_TEXT·CHAT·OWNER_TEXT 훑기 | 4 |
| `api/app/ingest/intake/probe_media.py` (신규) | DOC_IMAGE·AUDIO·VIDEO 훑기 | 5 |
| `api/app/ingest/intake/classify.py` (신규) | 분류 호출·응답 스키마·mock | 6 |
| `api/prompts/classify_intake.ko.txt` (신규) | 분류 프롬프트 | 6 |
| `supabase/migrations/20261011100000_w_intake_routing.sql` (신규) | `intake_route_decisions`·`owner_answer_attachments`·`sources.owner_hints`·`source_facts.ext` | 7 |
| `api/app/ingest/intake/records.py` (신규) | 판정 기록·첨부·칩 DB 함수 | 7 |
| `api/app/ingest/repository.py` (수정) | `insert_source_facts` 에 `ext` | 7 |
| `api/app/ingest/intake/plan.py` (신규) | 판정 → 추출 계획(거른 글·로직별 구간·NOTICE 구간) | 8 |
| `api/app/ingest/intake/route.py` (신규) | 자료 하나 또는 답변 묶음 훑기→분류→결정→기록 | 9·11 |
| `api/app/ingest/pipeline.py` (수정) | 분류 단계 연결, 캐시, NOTICE 보류, `INTAKE_NONE` | 9 |
| `api/app/ingest/fact_cards.py` (수정) | `REASON_INTAKE_NOTICE` | 9 |
| `api/app/ingest/job_worker.py` (수정) | `INTAKE_NONE` 메시지 | 9 |
| `api/app/ingest/router.py` (수정) | `owner_hints` 저장, 첨부 API | 10·12 |
| `api/app/ingest/owner_text.py` (수정) | 답변 글 판정 반영(NONE 건너뜀·NOTICE 보류) | 11 |
| `api/app/cards/owner_answer_worker.py` (수정) | 답변 묶음 분류, 첨부 작업 생성 | 11 |
| `web/lib/ingest-submit.ts`·`web/lib/api.ts`·`web/components/owner/owner-add-composer.tsx` (수정) | 종류 칩·hints 전송 | 10 |
| `web/components/owner/intake-hint-chips.tsx` (신규) | 칩 컴포넌트(업로드·답변 공용) | 10 |
| `web/components/owner/answer-question-sheet.tsx`·`web/app/owner/questions/page.tsx` (수정) | 답변 첨부 | 13 |
| `api/app/checklist/repository.py`·`scope.py` (수정) | 체크 항목 = 카드 제목 한 줄 | 14 |
| `web/components/checklist/today-screen.tsx`·`records-screen.tsx` (수정) | 카드 단위 행, 제목을 누르면 카드 상세 | 14 |
| `api/eval/intake/*.json`·`api/scripts/run_intake_classifier_eval.py`·`api/app/ingest/intake/evaluate.py` (신규) | 분류기 평가 하네스 | 15 |
| `api/scripts/build_consensus_reference.py` (수정)·`api/eval/consensus/recipe_runs.json` (신규) | 다수결 참조 일반화 | 16 |
| `api/scripts/verify_w_intake.py` (신규)·`verify_r_schema_rebuild.py` (가산) | 실제 DB 종단 검증 | 17 |
| 문서 | 로드맵 상태, 설계 §9 계획 결정, 이 계획 결과 | 17 |

---

### Task 1: 설정 · docx 확장자 · docx 읽기

**Files:**
- Modify: `api/app/config.py` (설정 클래스 안, `pdf_input_mode` 근처)
- Modify: `api/app/ingest/capabilities.py:7-12`
- Modify: `api/app/ingest/schemas.py:152-155` (`ScanMeta`)
- Create: `api/app/ingest/preprocess/docx.py`
- Modify: `api/app/ingest/pipeline.py` (`_preprocess_scan`, 다운로드 직후)
- Create: `supabase/migrations/20261011090000_w_docx_doc_type.sql`
- Test: `api/tests/test_wb_docx.py`

**Interfaces:**
- Produces: `docx.read_docx(path: Path) -> DocxRead`, `DocxRead(blocks: list[DocxBlock], skipped_images: int)`, `DocxBlock(kind: Literal["HEADING","PARA","TABLE_ROW"], text: str, index: int)`, `docx.UnsupportedDocument(Exception)`, `docx.block_line(b: DocxBlock) -> str`, `docx.to_text(read: DocxRead) -> str`. 설정 필드는 아래 Step 3 의 이름 그대로 쓴다.

- [ ] **Step 1: 기준선 기록.** `cd api && .venv/bin/python -m pytest -q tests 2>&1 | tail -3` 를 실행하고 passed·skipped·xfailed 수를 이 계획 맨 아래 "실행 기록"에 적는다. 이후 Task 들은 이 수에 새 테스트를 더한 값과 비교한다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# api/tests/test_wb_docx.py
"""Phase B — docx 확장자·읽기(표준 라이브러리). 합성 docx 를 테스트 안에서 만든다."""
import zipfile
from pathlib import Path

import pytest

from app.ingest import capabilities
from app.ingest.preprocess import docx
from app.ingest.schemas import ScanMeta

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _tbl(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows)
    return f"<w:tbl>{cells}</w:tbl>"


def make_docx(tmp_path: Path, body: str, name: str = "합성.docx") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_NS}><w:body>{body}</w:body></w:document>')
    return path


def test_scan_accepts_docx():
    assert "docx" in capabilities.SUPPORTED_EXTENSIONS["SCAN"]
    assert ScanMeta(doc_type="DOCX").doc_type == "DOCX"


def test_avi_hwp_not_supported():
    # 2026-10-11 사용자 확정: avi·hwp(hwpx) 는 이번에 하지 않는다
    every = {e for exts in capabilities.SUPPORTED_EXTENSIONS.values() for e in exts}
    assert not {"avi", "hwp", "hwpx"} & every


def test_read_docx_blocks_in_order(tmp_path):
    path = make_docx(tmp_path, _p("오픈 절차", "Heading1") + _p("의자를 내린다")
                     + _tbl([["메뉴", "샷"], ["음료Z", "2"]]) + _p(""))
    read = docx.read_docx(path)
    assert [(b.kind, b.text, b.index) for b in read.blocks] == [
        ("HEADING", "오픈 절차", 1), ("PARA", "의자를 내린다", 2),
        ("TABLE_ROW", "메뉴 | 샷", 3), ("TABLE_ROW", "음료Z | 2", 4)]


def test_korean_heading_style_counts_as_heading(tmp_path):
    read = docx.read_docx(make_docx(tmp_path, _p("마감", "제목1")))
    assert read.blocks[0].kind == "HEADING"


def test_to_text_marks_headings_and_rows(tmp_path):
    read = docx.read_docx(make_docx(tmp_path, _p("마감", "Heading2") + _tbl([["a", "b"]])))
    assert docx.to_text(read) == "## 마감\n\n| a | b |"


def test_broken_docx_is_unsupported(tmp_path):
    bad = tmp_path / "깨진.docx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(docx.UnsupportedDocument):
        docx.read_docx(bad)


def test_images_are_counted_not_read(tmp_path):
    body = '<w:p><w:r><w:drawing/></w:r><w:r><w:t>그림 아래 글</w:t></w:r></w:p>'
    read = docx.read_docx(make_docx(tmp_path, body))
    assert read.skipped_images == 1 and read.blocks[0].text == "그림 아래 글"
```

- [ ] **Step 3: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_docx.py` → `ModuleNotFoundError: app.ingest.preprocess.docx` 와 docx 미지원 단언 실패.

- [ ] **Step 4: 구현한다**

`capabilities.py`: `"SCAN": ("pdf", "jpg", "jpeg", "png", "docx"),`

`schemas.py` `ScanMeta`: `doc_type: Literal["PDF", "JPG", "PNG", "DOCX"]`

`config.py` (가산, `pdf_input_mode` 아래):

```python
    # ── Phase B 입구 분류(B-D2·B-D3). 시작값이다 — 분류기 평가로 조정한다 ──
    # 분류 모델. '공급자:모델' 형식(providers.parse_model_spec). 가장 싼 경량 모델로 바꾸는 것은 평가 뒤
    intake_classifier_model: str = "gemini:gemini-3.6-flash"
    intake_classifier_max_output_tokens: int = Field(default=2048, ge=256)
    # 훑기 상한: 글 자료 표본 전체 글자 수, 이미지 장수·긴 변, 음성·영상 STT 창
    intake_probe_text_chars: int = Field(default=3000, ge=200)
    intake_probe_max_images: int = Field(default=6, ge=1)
    intake_probe_image_px: int = Field(default=512, ge=128)
    intake_probe_av_windows: int = Field(default=3, ge=1)
    intake_probe_av_window_sec: int = Field(default=20, ge=5)
    intake_probe_video_keyframes: int = Field(default=5, ge=1)
    # 후보 구간 수 상한과 작은 구간 합치기 기준(글자)
    intake_max_sections: int = Field(default=12, ge=1)
    intake_min_section_chars: int = Field(default=80, ge=0)
    # 결정 규칙(B-D3a·B-D3b·B-D6)
    intake_owner_hint_boost: float = Field(default=0.15, ge=0, le=1)
    intake_multi_label_min: float = Field(default=0.35, ge=0, le=1)
    intake_ambiguous_top_min: float = Field(default=0.5, ge=0, le=1)
    intake_ambiguous_gap_min: float = Field(default=0.15, ge=0, le=1)
```

`api/app/ingest/preprocess/docx.py`:

```python
"""docx(zip+XML) 글자·제목·표 행 읽기 — 표준 라이브러리만 쓴다(Phase B, B-D2).

그림·수식은 읽지 않고 개수만 센다(범위 밖, 기록용). 열 수 없는 파일은 추정하지 않고 실패한다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal, NamedTuple
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class UnsupportedDocument(Exception):
    """읽을 수 없는 문서. 작업은 FAILED 로 멈춘다."""


class DocxBlock(NamedTuple):
    kind: Literal["HEADING", "PARA", "TABLE_ROW"]
    text: str
    index: int  # 1부터, 문서 순서. 위치 표시(LINE)에 쓴다


class DocxRead(NamedTuple):
    blocks: list[DocxBlock]
    skipped_images: int


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()


def _is_heading(p: ET.Element) -> bool:
    style = p.find(f"{_W}pPr/{_W}pStyle")
    value = style.get(f"{_W}val", "") if style is not None else ""
    return value.lower().startswith(("heading", "title")) or value.startswith("제목")


def read_docx(path: Path) -> DocxRead:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise UnsupportedDocument(f"docx 를 열 수 없다: {exc}") from exc
    body = root.find(f"{_W}body")
    blocks: list[DocxBlock] = []
    images = 0
    for el in list(body) if body is not None else []:
        if el.tag == f"{_W}p":
            images += len(list(el.iter(f"{_W}drawing")))
            text = _para_text(el)
            if text:
                kind = "HEADING" if _is_heading(el) else "PARA"
                blocks.append(DocxBlock(kind, text, len(blocks) + 1))
        elif el.tag == f"{_W}tbl":
            for tr in el.iter(f"{_W}tr"):
                cells = [" ".join(t for t in (_para_text(p) for p in tc.iter(f"{_W}p")) if t)
                         for tc in tr.findall(f"{_W}tc")]
                if any(cells):
                    blocks.append(DocxBlock("TABLE_ROW", " | ".join(cells), len(blocks) + 1))
    return DocxRead(blocks, images)


def block_line(b: DocxBlock) -> str:
    if b.kind == "HEADING":
        return f"## {b.text}"
    if b.kind == "TABLE_ROW":
        return f"| {b.text} |"
    return b.text


def to_text(read: DocxRead) -> str:
    """추출 입력 글. 블록을 빈 줄로 잇는다(구간 묶음 글을 다시 이어도 같은 글이 되게 — Task 8)."""
    return "\n\n".join(block_line(b) for b in read.blocks)
```

`pipeline._preprocess_scan` — `path = await _download(...)` 바로 다음, LAYOUT 분기 **앞**에 넣는다(docx 는 구역 경로로 가지 않는다):

```python
    if path.suffix.lower() == ".docx":
        from app.ingest.preprocess import docx
        read = docx.read_docx(path)  # UnsupportedDocument → process_source 가 FAILED 로 적는다
        text = docx.to_text(read)
        if read.skipped_images:
            logger.info("docx 그림 %d개는 읽지 않았다 source=%s", read.skipped_images, source_id)
        async with pool.acquire() as conn:
            await repo.update_scan_result(conn, source_id, page_count=1,
                                          ocr_text=text or None, ocr_engine="docx")
        if not text:
            raise docx.UnsupportedDocument("docx 에 읽을 글이 없다")
        return text, [], []
```

`supabase/migrations/20261011090000_w_docx_doc_type.sql`:

```sql
-- Phase B — 문서 자료에 docx 를 받는다. check 제약만 넓힌다(가산).
alter table source_scan drop constraint if exists source_scan_doc_type_check;
alter table source_scan add constraint source_scan_doc_type_check
  check (doc_type in ('PDF', 'JPG', 'PNG', 'DOCX'));
```

- [ ] **Step 5: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_docx.py` → 7 passed. 이어서 `cd api && .venv/bin/python -m pytest -q tests -k "capabilit or upload or scan"` → 회귀가 없어야 한다.

- [ ] **Step 6: 변경을 확인한다.** `git status --short` 결과가 위 Files 범위와 같아야 한다.

---

### Task 2: IR · 등록표

**Files:**
- Create: `api/app/ingest/intake/__init__.py` (빈 docstring)
- Create: `api/app/ingest/intake/ir.py`
- Create: `api/app/ingest/intake/registry.py`
- Test: `api/tests/test_wb_intake_registry.py`

**Interfaces:**
- Produces:
  - `ir.Locator(kind: Literal["PAGE","TIME","DATE","LINE","WHOLE"], start: str, end: str)`, `.as_dict() -> dict`
  - `ir.Candidate(candidate_id: str, locator: Locator, text: str, images: tuple[Path, ...] = (), sampled: bool = True)`
  - `ir.ProbeResult(normalizer: str, candidates: tuple[Candidate, ...])`, `.sampled() -> tuple[Candidate, ...]`, `.summary() -> dict`, `.sample_hash() -> str`(64자 hex)
  - `registry.LOGICS`, `registry.CARD_LOGICS`, `registry.NORMALIZERS`, `registry.SECTIONED_NORMALIZERS`, `registry.EXTRACTORS: dict[str, str]`, `registry.registered_logics() -> tuple[str, ...]`, `registry.normalizer_for(source_type: str, ext: str, *, pdf_has_text: bool) -> str`, `registry.JOINER: dict[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_registry.py
"""Phase B — 공통 중간 형식(IR)과 등록표(B-D5)."""
import pytest

from app.ingest.intake import ir, registry


def test_logics_and_normalizers():
    assert registry.LOGICS == ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE")
    assert registry.CARD_LOGICS == ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE")
    assert set(registry.NORMALIZERS) == {"DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT"}
    # 2026-10-11 사용자 확정: 글 자료만 구간별로 추출한다
    assert registry.SECTIONED_NORMALIZERS == frozenset({"DOC_TEXT", "CHAT", "OWNER_TEXT"})


def test_only_recipe_registered_now():
    assert registry.registered_logics() == ("RECIPE",)


@pytest.mark.parametrize("source_type, ext, has_text, expected", [
    ("VOICE", "m4a", False, "AUDIO"),
    ("VIDEO", "mp4", False, "VIDEO"),
    ("KAKAO", "txt", False, "CHAT"),
    ("KAKAO", "png", False, "CHAT"),
    ("SCAN", "pdf", True, "DOC_TEXT"),
    ("SCAN", "pdf", False, "DOC_IMAGE"),
    ("SCAN", "jpg", False, "DOC_IMAGE"),
    ("SCAN", "docx", False, "DOC_TEXT"),
    ("OWNER_TEXT", "", False, "OWNER_TEXT"),
])
def test_normalizer_for(source_type, ext, has_text, expected):
    assert registry.normalizer_for(source_type, ext, pdf_has_text=has_text) == expected


def test_unknown_extension_raises():
    with pytest.raises(ValueError):
        registry.normalizer_for("SCAN", "hwp", pdf_has_text=False)


def test_probe_summary_and_hash_ignore_unsampled_text():
    loc = ir.Locator("PAGE", "1", "1")
    a = ir.ProbeResult("DOC_TEXT", (ir.Candidate("c1", loc, "가나다"),
                                    ir.Candidate("c2", ir.Locator("PAGE", "2", "2"), "", sampled=False)))
    assert a.summary() == {"normalizer": "DOC_TEXT", "candidates": 2, "sampled": ["c1"],
                           "chars": 3, "images": 0}
    b = ir.ProbeResult("DOC_TEXT", (ir.Candidate("c1", loc, "가나다"),))
    assert len(a.sample_hash()) == 64
    assert a.sample_hash() != b.sample_hash()  # 후보 구성이 다르면 다르다
```

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_registry.py` → `ModuleNotFoundError: app.ingest.intake`

- [ ] **Step 3: 구현한다**

```python
# api/app/ingest/intake/ir.py
"""공통 중간 형식(IR) — 분류기와 로직 추출기는 파일이 아니라 이것만 본다(설계 4-2)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LocatorKind = Literal["PAGE", "TIME", "DATE", "LINE", "WHOLE"]


@dataclass(frozen=True)
class Locator:
    kind: LocatorKind
    start: str
    end: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class Candidate:
    """코드가 만든 경계 후보 하나. 표본이 아니면 text·images 가 비고 sampled=False 다."""
    candidate_id: str
    locator: Locator
    text: str
    images: tuple[Path, ...] = ()
    sampled: bool = True


@dataclass(frozen=True)
class ProbeResult:
    normalizer: str
    candidates: tuple[Candidate, ...]

    def sampled(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.sampled)

    def summary(self) -> dict:
        """기록용 요약. 원문은 담지 않는다(B-D6)."""
        sampled = self.sampled()
        return {"normalizer": self.normalizer, "candidates": len(self.candidates),
                "sampled": [c.candidate_id for c in sampled],
                "chars": sum(len(c.text) for c in sampled),
                "images": sum(len(c.images) for c in sampled)}

    def sample_hash(self) -> str:
        h = hashlib.sha256(self.normalizer.encode())
        for c in self.candidates:
            h.update(f"\x00{c.candidate_id}\x00{c.locator.kind}:{c.locator.start}-{c.locator.end}"
                     f"\x00{int(c.sampled)}\x00{c.text}".encode())
            for img in c.images:
                h.update(hashlib.sha256(img.read_bytes()).digest())
        return h.hexdigest()
```

```python
# api/app/ingest/intake/registry.py
"""등록표(B-D5) — 확장자→정규화기, 로직→추출기. 확장자 × 로직 곱을 만들지 않는다(B-U9)."""
from __future__ import annotations

LOGICS = ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE")
CARD_LOGICS = ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE")
NORMALIZERS = ("DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT")
# 구간별로 골라 추출하는 정규화기(2026-10-11 사용자 확정). 나머지는 자료 전체를 1위 로직으로
SECTIONED_NORMALIZERS = frozenset({"DOC_TEXT", "CHAT", "OWNER_TEXT"})
# 구간 글을 다시 이을 때 쓰는 구분자 — 전처리 결과 글과 같은 방식이어야 한다(Task 8)
JOINER = {"DOC_TEXT": "\n\n", "CHAT": "\n", "OWNER_TEXT": "\n\n"}

# 로직 → 추출기. 값은 기록용 추출기 이름이다. 이번에는 RECIPE 만 등록한다(B-D5)
EXTRACTORS: dict[str, str] = {"RECIPE": "extract_facts.ko"}

_BY_TYPE = {
    "VOICE": {"mp3": "AUDIO", "m4a": "AUDIO", "wav": "AUDIO"},
    "VIDEO": {"mp4": "VIDEO", "mov": "VIDEO"},
    "KAKAO": {"txt": "CHAT", "jpg": "CHAT", "jpeg": "CHAT", "png": "CHAT"},
    "SCAN": {"jpg": "DOC_IMAGE", "jpeg": "DOC_IMAGE", "png": "DOC_IMAGE", "docx": "DOC_TEXT"},
}


def registered_logics() -> tuple[str, ...]:
    return tuple(l for l in CARD_LOGICS if l in EXTRACTORS)


def normalizer_for(source_type: str, ext: str, *, pdf_has_text: bool) -> str:
    """입력 종류와 파일 검사로 코드가 가른다. 모델을 부르지 않는다(설계 4-2)."""
    if source_type == "OWNER_TEXT":
        return "OWNER_TEXT"
    if source_type == "SCAN" and ext == "pdf":
        return "DOC_TEXT" if pdf_has_text else "DOC_IMAGE"
    try:
        return _BY_TYPE[source_type][ext]
    except KeyError:
        raise ValueError(f"정규화기가 없는 입력이다: {source_type} .{ext or '없음'}") from None
```

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_registry.py` → 13 passed.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 3: 결정 규칙 (순수 함수)

**Files:**
- Create: `api/app/ingest/intake/decide.py`
- Test: `api/tests/test_wb_intake_decide.py`

**Interfaces:**
- Consumes: `ir.Candidate`, `registry.LOGICS`·`CARD_LOGICS`·`registered_logics()`
- Produces:
  - `Ranked(logic: str, score: float)`
  - `Thresholds(boost: float, multi_label_min: float, ambiguous_top_min: float, ambiguous_gap_min: float)`, `Thresholds.from_settings(s) -> Thresholds`
  - `SectionDecision(candidate_id, logic, extractors: tuple[str, ...], ambiguous, fallback_unregistered, hint_changed_decision, inherited_from: str | None, model_ranking: tuple[Ranked, ...], boosted_ranking: tuple[Ranked, ...])`, `.as_dict() -> dict`, `SectionDecision.from_dict(d) -> SectionDecision`
  - `IntakeClassificationError(Exception)`
  - `decide_all(candidates: Sequence[Candidate], model: Mapping[str, Sequence[Ranked]], *, hints: Sequence[str], th: Thresholds, registered: Sequence[str]) -> list[SectionDecision]`
  - `source_decision(decisions: Sequence[SectionDecision], *, hints, th, registered) -> SectionDecision` (candidate_id `"source"`)

규칙(설계 B-D3a·B-D3b-2·B-D4):
1. 가산: 점주가 고른 로직의 점수에 `boost` 를 더하고 1.0 에서 자른다. 순위는 점수 내림차순, 같은 점수는 `LOGICS` 순서다.
2. 최종 로직 = 가산 순위 1위다. 애매해도 1위로 간다(기본 로직으로 떨어뜨리지 않는다).
3. `ambiguous` = 1위 점수 < `ambiguous_top_min`, 또는 1·2위 차 < `ambiguous_gap_min`.
4. 추출기 해석 `resolve(logic)`: 등록돼 있으면 그대로다. 아니면 순위에서 등록 로직 중 가장 높은 것을 쓰고, 순위에 등록 로직이 없으면 `registered[0]` 을 쓴다. 등록되지 않아 대체된 경우 `fallback_unregistered=True` 다.
5. `extractors`: NONE 이면 `()`. NOTICE 이면 `(resolve(NOTICE),)` 이고 사실은 보류된다(Task 9). 카드 로직이면 `resolve(1위)` 에 더해, 2위가 카드 로직이고 점수 ≥ `multi_label_min` 이면 `resolve(2위)` 를 추가한다(중복 제거, 순서 유지).
6. `hint_changed_decision` = 모델 1위 로직 ≠ 가산 1위 로직.
7. 표본 후보가 모델 출력에 없으면 `IntakeClassificationError` 를 올린다. 표본이 아닌 후보는 가장 가까운 표본 후보(후보 순서 거리, 같으면 앞쪽)의 판정을 복사하고 `inherited_from` 을 단다.
8. 자료 단위 판정: 상속이 아닌 판정들의 **가산 전 모델 점수** 평균을 로직별로 낸다(없는 로직은 0). 여기에 같은 가산·규칙을 적용한다. 모든 구간이 NONE 이면 자료도 NONE 이다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_decide.py
"""Phase B — 결정 규칙(B-D3a 가산·B-D3b 다중·B-D4 가장 가까운 로직). 모델 호출 없음."""
import pytest

from app.ingest.intake import decide
from app.ingest.intake.decide import Ranked, Thresholds
from app.ingest.intake.ir import Candidate, Locator

TH = Thresholds(boost=0.15, multi_label_min=0.35, ambiguous_top_min=0.5, ambiguous_gap_min=0.15)
REG = ("RECIPE",)


def _c(cid, sampled=True):
    return Candidate(cid, Locator("PAGE", cid, cid), "글" if sampled else "", sampled=sampled)


def _r(*pairs):
    return [Ranked(l, s) for l, s in pairs]


def _one(ranking, hints=(), registered=REG):
    return decide.decide_all([_c("c1")], {"c1": _r(*ranking)}, hints=hints, th=TH,
                             registered=registered)[0]


def test_top_logic_wins_even_if_low():
    d = _one([("RECIPE", 0.3), ("POLICY", 0.25)])
    assert d.logic == "RECIPE" and d.ambiguous and d.extractors == ("RECIPE",)


def test_unregistered_falls_back_to_nearest_registered():
    d = _one([("PROCEDURE", 0.8), ("RECIPE", 0.1)])
    assert d.logic == "PROCEDURE" and d.extractors == ("RECIPE",) and d.fallback_unregistered


def test_unregistered_without_registered_in_ranking_uses_first_registered():
    d = _one([("POLICY", 0.9)])
    assert d.extractors == ("RECIPE",) and d.fallback_unregistered


def test_none_has_no_extractor():
    d = _one([("NONE", 0.9), ("RECIPE", 0.05)])
    assert d.logic == "NONE" and d.extractors == ()


def test_notice_keeps_logic_and_one_extractor():
    d = _one([("NOTICE", 0.7), ("POLICY", 0.2)])
    assert d.logic == "NOTICE" and d.extractors == ("RECIPE",)


def test_hint_boost_flips_close_call_and_is_recorded():
    d = _one([("RECIPE", 0.45), ("PROCEDURE", 0.40)], hints=("PROCEDURE",))
    assert d.logic == "PROCEDURE" and d.hint_changed_decision
    assert d.model_ranking[0].logic == "RECIPE"


def test_hint_does_not_beat_clear_content():
    d = _one([("RECIPE", 0.9), ("PROCEDURE", 0.05)], hints=("PROCEDURE",))
    assert d.logic == "RECIPE" and not d.hint_changed_decision


def test_multi_label_two_registered_extractors_dedup():
    reg = ("RECIPE", "POLICY")
    d = _one([("RECIPE", 0.5), ("POLICY", 0.4)], registered=reg)
    assert d.extractors == ("RECIPE", "POLICY")
    d2 = _one([("RECIPE", 0.5), ("PROCEDURE", 0.4)])  # 둘 다 RECIPE 로 풀리면 한 번만
    assert d2.extractors == ("RECIPE",)


def test_notice_never_second_label():
    reg = ("RECIPE",)
    d = _one([("RECIPE", 0.5), ("NOTICE", 0.45)], registered=reg)
    assert d.extractors == ("RECIPE",)


def test_missing_sampled_candidate_raises():
    with pytest.raises(decide.IntakeClassificationError):
        decide.decide_all([_c("c1"), _c("c2")], {"c1": _r(("RECIPE", 0.9))}, hints=(), th=TH,
                          registered=REG)


def test_unsampled_inherits_nearest_sampled_earlier_on_tie():
    cands = [_c("c1"), _c("c2", sampled=False), _c("c3")]
    out = decide.decide_all(cands, {"c1": _r(("RECIPE", 0.9)), "c3": _r(("NONE", 0.9))},
                            hints=(), th=TH, registered=REG)
    assert [d.logic for d in out] == ["RECIPE", "RECIPE", "NONE"]
    assert out[1].inherited_from == "c1"


def test_source_decision_averages_model_scores():
    cands = [_c("c1"), _c("c2")]
    out = decide.decide_all(cands, {"c1": _r(("RECIPE", 0.8), ("NONE", 0.2)),
                                    "c2": _r(("NONE", 0.9), ("RECIPE", 0.1))},
                            hints=(), th=TH, registered=REG)
    src = decide.source_decision(out, hints=(), th=TH, registered=REG)
    assert src.candidate_id == "source" and src.logic == "NONE"  # 평균 NONE 0.55 > RECIPE 0.45


def test_all_none_source_is_none():
    out = decide.decide_all([_c("c1")], {"c1": _r(("NONE", 0.6))}, hints=(), th=TH, registered=REG)
    assert decide.source_decision(out, hints=(), th=TH, registered=REG).logic == "NONE"


def test_round_trip_dict():
    d = _one([("PROCEDURE", 0.8), ("RECIPE", 0.1)])
    assert decide.SectionDecision.from_dict(d.as_dict()) == d
```

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_decide.py` → ImportError.

- [ ] **Step 3: 구현한다**

```python
# api/app/ingest/intake/decide.py
"""분류 결정 규칙 — 점주 칩 가산(B-D3a), 다중 라벨(B-D3b), 가장 가까운 로직(B-D4). 순수 함수."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.ingest.intake.ir import Candidate
from app.ingest.intake.registry import CARD_LOGICS, LOGICS


class IntakeClassificationError(Exception):
    """분류를 믿을 수 없다. 조용히 다른 로직으로 보내지 않고 작업을 실패시킨다."""


@dataclass(frozen=True)
class Ranked:
    logic: str
    score: float


@dataclass(frozen=True)
class Thresholds:
    boost: float
    multi_label_min: float
    ambiguous_top_min: float
    ambiguous_gap_min: float

    @classmethod
    def from_settings(cls, s) -> "Thresholds":
        return cls(s.intake_owner_hint_boost, s.intake_multi_label_min,
                   s.intake_ambiguous_top_min, s.intake_ambiguous_gap_min)


@dataclass(frozen=True)
class SectionDecision:
    candidate_id: str
    logic: str
    extractors: tuple[str, ...]
    ambiguous: bool
    fallback_unregistered: bool
    hint_changed_decision: bool
    inherited_from: str | None
    model_ranking: tuple[Ranked, ...]
    boosted_ranking: tuple[Ranked, ...]

    def as_dict(self) -> dict:
        return {"candidate_id": self.candidate_id, "logic": self.logic,
                "extractors": list(self.extractors), "ambiguous": self.ambiguous,
                "fallback_unregistered": self.fallback_unregistered,
                "hint_changed_decision": self.hint_changed_decision,
                "inherited_from": self.inherited_from,
                "model_ranking": [[r.logic, r.score] for r in self.model_ranking],
                "boosted_ranking": [[r.logic, r.score] for r in self.boosted_ranking]}

    @classmethod
    def from_dict(cls, d: dict) -> "SectionDecision":
        return cls(d["candidate_id"], d["logic"], tuple(d["extractors"]), d["ambiguous"],
                   d["fallback_unregistered"], d["hint_changed_decision"], d["inherited_from"],
                   tuple(Ranked(l, s) for l, s in d["model_ranking"]),
                   tuple(Ranked(l, s) for l, s in d["boosted_ranking"]))


def _sort(ranking: Sequence[Ranked]) -> tuple[Ranked, ...]:
    return tuple(sorted(ranking, key=lambda r: (-r.score, LOGICS.index(r.logic))))


def _boost(ranking: Sequence[Ranked], hints: Sequence[str], amount: float) -> tuple[Ranked, ...]:
    chosen = set(hints)
    return _sort([Ranked(r.logic, min(1.0, r.score + amount)) if r.logic in chosen else r
                  for r in ranking])


def _resolve(logic: str, ranking: Sequence[Ranked], registered: Sequence[str]) -> tuple[str, bool]:
    if logic in registered:
        return logic, False
    for r in ranking:
        if r.logic in registered:
            return r.logic, True
    return registered[0], True


def _decide(cid: str, model: Sequence[Ranked], *, hints, th: Thresholds,
            registered: Sequence[str]) -> SectionDecision:
    model_sorted = _sort(model)
    boosted = _boost(model_sorted, hints, th.boost)
    if not boosted:
        raise IntakeClassificationError(f"구간 {cid} 의 순위가 비었다")
    top = boosted[0]
    second = boosted[1] if len(boosted) > 1 else None
    ambiguous = top.score < th.ambiguous_top_min or (
        second is not None and top.score - second.score < th.ambiguous_gap_min)
    fallback = False
    if top.logic == "NONE":
        extractors: tuple[str, ...] = ()
    else:
        first, fallback = _resolve(top.logic, boosted, registered)
        extractors = (first,)
        if (top.logic in CARD_LOGICS and second is not None and second.logic in CARD_LOGICS
                and second.score >= th.multi_label_min):
            extra, extra_fallback = _resolve(second.logic, boosted, registered)
            if extra not in extractors:
                extractors += (extra,)
                fallback = fallback or extra_fallback
    return SectionDecision(cid, top.logic, extractors, ambiguous, fallback,
                           model_sorted[0].logic != top.logic, None, model_sorted, boosted)


def decide_all(candidates: Sequence[Candidate], model: Mapping[str, Sequence[Ranked]], *,
               hints: Sequence[str], th: Thresholds,
               registered: Sequence[str]) -> list[SectionDecision]:
    own: dict[str, SectionDecision] = {}
    for c in candidates:
        if not c.sampled:
            continue
        if c.candidate_id not in model:
            raise IntakeClassificationError(f"분류 결과에 구간 {c.candidate_id} 이 없다")
        own[c.candidate_id] = _decide(c.candidate_id, model[c.candidate_id], hints=hints, th=th,
                                      registered=registered)
    if not own:
        raise IntakeClassificationError("표본 구간이 없다")
    sampled_pos = [i for i, c in enumerate(candidates) if c.sampled]
    out = []
    for i, c in enumerate(candidates):
        if c.sampled:
            out.append(own[c.candidate_id])
            continue
        nearest = min(sampled_pos, key=lambda j: (abs(j - i), j))
        src = own[candidates[nearest].candidate_id]
        out.append(SectionDecision(c.candidate_id, src.logic, src.extractors, src.ambiguous,
                                   src.fallback_unregistered, src.hint_changed_decision,
                                   src.candidate_id, src.model_ranking, src.boosted_ranking))
    return out


def source_decision(decisions: Sequence[SectionDecision], *, hints: Sequence[str],
                    th: Thresholds, registered: Sequence[str]) -> SectionDecision:
    """자료 전체를 한 로직으로 다루는 정규화기용(2026-10-11 결정). 모델 점수 평균에 같은 규칙."""
    own = [d for d in decisions if d.inherited_from is None]
    if own and all(d.logic == "NONE" for d in own):
        avg = [Ranked("NONE", 1.0)]
    else:
        totals = {l: 0.0 for l in LOGICS}
        for d in own:
            for r in d.model_ranking:
                totals[r.logic] += r.score
        avg = [Ranked(l, round(v / max(1, len(own)), 4)) for l, v in totals.items() if v > 0]
    return _decide("source", avg, hints=hints, th=th, registered=registered)
```

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_decide.py` → 14 passed.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 4: 글 자료 후보 묶기 · 글 훑기 (DOC_TEXT · CHAT · OWNER_TEXT)

**Files:**
- Create: `api/app/ingest/intake/grouping.py`
- Create: `api/app/ingest/intake/probe_text.py`
- Modify: `api/app/ingest/preprocess/document.py` (쪽별 글을 돌려주는 `pdf_pages` 추가, `read_pdf` 동작 불변)
- Test: `api/tests/test_wb_intake_probe_text.py`

**Interfaces:**
- Consumes: `ir.*`, `docx.DocxRead`·`docx.block_line`, `owner_text.compose_text`
- Produces:
  - `grouping.Group(candidate_id: str, locator: Locator, units: tuple[str, ...])`. `units` 는 추출 입력 글의 단위 조각이다. 이어 붙이면 그 구간의 전체 글이 된다.
  - `grouping.even_indices(n: int, k: int) -> list[int]`: 0부터 센다. 처음·끝을 포함하고 고른 간격으로 고른다. `k >= n` 이면 전부다.
  - `grouping.group_pdf_pages(blocks: Sequence[tuple[int, str]], *, max_sections: int) -> list[Group]`: 입력은 `read_pdf` 와 같은 `[N쪽]\n글` 블록이다.
  - `grouping.group_docx(read: DocxRead, *, max_sections: int, min_chars: int) -> list[Group]`
  - `grouping.group_chat(parsed_text: str, *, max_sections: int) -> list[Group]`: 메시지 단위(`[`로 시작하는 줄 + 이어지는 줄)를 날짜(`MM-DD`)로 묶는다.
  - `grouping.sections_text(groups: Sequence[Group], joiner: str) -> dict[str, str]`
  - `probe_text.probe_groups(normalizer: str, groups: Sequence[Group], *, budget_chars: int) -> ProbeResult`: 모든 후보가 표본이다. 후보마다 앞부분 `budget_chars // len(groups)` 자를 쓴다.
  - `probe_text.probe_owner_text(question: str, answer: str) -> ProbeResult`: WHOLE 후보 하나, id `c1`
  - `document.pdf_pages(path: Path) -> PdfPages(blocks: list[tuple[int, str]], page_count: int, visual_pages: list[int], has_text: bool)`. `read_pdf` 와 같은 판정을 하고, 글이 읽힌 쪽만 `(쪽, "[N쪽]\n글")` 블록으로 준다.

묶기 규칙: 후보가 `max_sections` 를 넘으면 이웃한 단위를 고르게 합쳐 `max_sections` 개로 만든다(앞쪽 묶음이 같거나 하나 더 많다). docx 는 HEADING 에서 새 구간을 시작하고, 표 행이 이어지는 동안은 한 구간이다. `min_chars` 보다 짧은 구간은 앞 구간에 합친다(첫 구간은 다음과 합친다). 후보 id 는 `c1..cN` 이다. 위치는 PDF 가 `PAGE 첫쪽~끝쪽`, docx 가 `LINE 첫블록~끝블록`, 카톡이 `DATE 첫날~끝날` 이다.

**같은 글 보장:** `"\n\n".join(units of all groups)` 가 PDF 는 `read_pdf(...).text`, docx 는 `docx.to_text(read)` 와 같아야 한다. 카톡은 `"\n".join(...)` 가 `parsed_text` 와 같아야 한다(Review Focus 4).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_probe_text.py
"""Phase B — 글 자료 경계 후보(코드가 만든다)와 훑기 표본. 모델 호출 없음."""
from app.ingest.intake import grouping, probe_text
from app.ingest.preprocess import docx
from app.ingest.preprocess.docx import DocxBlock, DocxRead


def test_even_indices_keeps_first_middle_last():
    assert grouping.even_indices(10, 3) == [0, 4, 9]  # 4 = round(4.5) 아래쪽
    assert grouping.even_indices(2, 5) == [0, 1]
    assert grouping.even_indices(1, 1) == [0]


def test_pdf_pages_merge_to_max_sections_and_rejoin_identically():
    blocks = [(n, f"[{n}쪽]\n쪽{n} 내용") for n in range(1, 8)]
    groups = grouping.group_pdf_pages(blocks, max_sections=3)
    assert [g.candidate_id for g in groups] == ["c1", "c2", "c3"]
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "3"), ("4", "5"), ("6", "7")]
    assert "\n\n".join(u for g in groups for u in g.units) == "\n\n".join(b for _, b in blocks)


def test_docx_splits_on_headings_and_merges_short():
    read = DocxRead([DocxBlock("HEADING", "오픈", 1), DocxBlock("PARA", "가" * 100, 2),
                     DocxBlock("HEADING", "짧음", 3),
                     DocxBlock("HEADING", "레시피", 4), DocxBlock("TABLE_ROW", "음료Z | 2", 5),
                     DocxBlock("TABLE_ROW", "나" * 100, 6)], 0)
    groups = grouping.group_docx(read, max_sections=12, min_chars=80)
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "3"), ("4", "6")]
    assert "\n\n".join(u for g in groups for u in g.units) == docx.to_text(read)


def test_chat_groups_by_date_keep_continuation_lines():
    text = "[08-01 09:00] 사장: 우유 2단\n이어지는 줄\n[08-01 10:00] 직원: 네\n[#3] [08-02 09:00] 사장: 마감"
    groups = grouping.group_chat(text, max_sections=12)
    assert [(g.locator.kind, g.locator.start, g.locator.end) for g in groups] == [
        ("DATE", "08-01", "08-01"), ("DATE", "08-02", "08-02")]
    assert "\n".join(u for g in groups for u in g.units) == text


def test_probe_groups_budget_and_all_sampled():
    blocks = [(n, f"[{n}쪽]\n" + "가" * 2000) for n in range(1, 4)]
    probe = probe_text.probe_groups("DOC_TEXT", grouping.group_pdf_pages(blocks, max_sections=12),
                                    budget_chars=3000)
    assert all(c.sampled for c in probe.candidates)
    assert all(len(c.text) <= 1000 for c in probe.candidates)
    assert probe.summary()["chars"] <= 3000


def test_probe_owner_text_whole():
    probe = probe_text.probe_owner_text("시럽 어디?", "창고 2번 선반")
    (c,) = probe.candidates
    assert c.candidate_id == "c1" and c.locator.kind == "WHOLE" and "창고 2번 선반" in c.text
```

PDF `pdf_pages` 는 Task 1 의 합성 문서 방식으로 만들기 어렵다(글자 층 PDF 생성 도구가 없다). 그래서 테스트는 `read_pdf` 와 같은 결과를 내는지만 단언한다. 기존 `read_pdf` 테스트가 쓰는 픽스처를 먼저 찾는다(`grep -rn "read_pdf" api/tests`). 픽스처가 있으면 `test_pdf_pages_matches_read_pdf` 를 추가해 `"\n\n".join(b for _, b in pdf_pages(p).blocks) == read_pdf(p).text`, `visual_pages`·`page_count` 가 같은지 단언한다. 없으면 `pypdf.PdfReader` 를 `unittest.mock.patch` 해서 쪽 객체 대역(`extract_text`, `images`)으로 같은 단언을 한다.

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_probe_text.py` → ImportError.

- [ ] **Step 3: 구현한다.** `document.py` 는 `read_pdf` 의 쪽 판정 루프를 `pdf_pages` 로 옮긴다. `read_pdf` 는 `pdf_pages` 결과로 같은 `PdfRead` 를 만든다(글 부족 시 전체 그림 처리 규칙 그대로. 그때 `has_text=False`, `blocks=[]`). 기존 `read_pdf` 테스트가 그대로 통과해야 한다.

```python
# api/app/ingest/intake/grouping.py
"""글 자료 경계 후보 — 코드가 먼저 만든다(B-D3b-1). probe 와 본 추출이 같은 묶음을 쓴다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.ingest.intake.ir import Locator
from app.ingest.preprocess.docx import DocxRead, block_line

_CHAT_HEAD = re.compile(r"^(?:\[#\d+\] )?\[(\d{2}-\d{2}) \d{2}:\d{2}\]")


@dataclass(frozen=True)
class Group:
    candidate_id: str
    locator: Locator
    units: tuple[str, ...]


def even_indices(n: int, k: int) -> list[int]:
    if k >= n:
        return list(range(n))
    if k == 1:
        return [0]
    return sorted({int((n - 1) * i / (k - 1)) for i in range(k)})


def _merge(parts: list[tuple[str, str, tuple[str, ...]]], max_sections: int, kind: str
           ) -> list[Group]:
    """(시작, 끝, 단위들) 목록을 max_sections 개 이하로 고르게 합친다."""
    n = len(parts)
    size, extra = divmod(n, max_sections) if n > max_sections else (1, 0)
    out, i = [], 0
    while i < n:
        take = size + (1 if len(out) < extra else 0)
        chunk = parts[i:i + take]
        out.append(Group(f"c{len(out) + 1}", Locator(kind, chunk[0][0], chunk[-1][1]),
                         tuple(u for _, _, units in chunk for u in units)))
        i += take
    return out


def group_pdf_pages(blocks: Sequence[tuple[int, str]], *, max_sections: int) -> list[Group]:
    return _merge([(str(n), str(n), (b,)) for n, b in blocks], max_sections, "PAGE")


def group_docx(read: DocxRead, *, max_sections: int, min_chars: int) -> list[Group]:
    runs: list[list] = []
    for b in read.blocks:
        new = (not runs or b.kind == "HEADING"
               or (b.kind != "TABLE_ROW" and runs[-1][-1].kind == "TABLE_ROW"))
        if new:
            runs.append([b])
        else:
            runs[-1].append(b)
    def chars(blocks) -> int:
        return sum(len(x.text) for x in blocks)

    # 짧은 구간은 앞 구간에 합친다. 첫 구간이 짧으면 다음 구간 앞에 붙인다
    merged: list[list] = []
    for run in runs:
        if merged and chars(run) < min_chars:
            merged[-1].extend(run)
        else:
            merged.append(list(run))
    if len(merged) > 1 and chars(merged[0]) < min_chars:
        first = merged.pop(0)  # 오른쪽이 먼저 평가되므로 merged[1][:0] = merged.pop(0) 로 쓰면 셋째 구간에 붙는다
        merged[0][:0] = first
    return _merge([(str(r[0].index), str(r[-1].index), tuple(block_line(b) for b in r))
                   for r in merged], max_sections, "LINE")


def group_chat(parsed_text: str, *, max_sections: int) -> list[Group]:
    days: list[tuple[str, list[str]]] = []
    for line in parsed_text.split("\n"):
        m = _CHAT_HEAD.match(line)
        if m and (not days or days[-1][0] != m.group(1)):
            days.append((m.group(1), [line]))
        elif days:
            days[-1][1].append(line)
        else:
            days.append(("", [line]))
    return _merge([(d, d, ("\n".join(lines),)) for d, lines in days], max_sections, "DATE")


def sections_text(groups: Sequence[Group], joiner: str) -> dict[str, str]:
    return {g.candidate_id: joiner.join(g.units) for g in groups}
```

```python
# api/app/ingest/intake/probe_text.py
"""글 자료 훑기(B-D2 ①) — 무료. 후보마다 앞부분만 상한 안에서."""
from __future__ import annotations

from typing import Sequence

from app.ingest.intake.grouping import Group
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def probe_groups(normalizer: str, groups: Sequence[Group], *, budget_chars: int) -> ProbeResult:
    per = max(1, budget_chars // max(1, len(groups)))
    return ProbeResult(normalizer, tuple(
        Candidate(g.candidate_id, g.locator, "\n".join(g.units)[:per]) for g in groups))


def probe_owner_text(question: str, answer: str) -> ProbeResult:
    from app.ingest.owner_text import compose_text
    return ProbeResult("OWNER_TEXT", (
        Candidate("c1", Locator("WHOLE", "", ""), compose_text(question, answer)),))
```

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_probe_text.py tests -k "pdf or document or probe_text"` → 새 테스트가 통과하고 기존 PDF 테스트에 회귀가 없어야 한다.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 5: 미디어 훑기 (DOC_IMAGE · AUDIO · VIDEO)

**Files:**
- Create: `api/app/ingest/intake/probe_media.py`
- Test: `api/tests/test_wb_intake_probe_media.py`

**Interfaces:**
- Consumes: `grouping.even_indices`, `ir.*`, `preprocess.audio.probe`·`transcribe_detailed`·`require_ffmpeg`, `preprocess.video.probe`, `layout.pages._render`(PDF 쪽 렌더링)
- Produces (외부 호출은 주입 가능한 인자로 받는다 — 테스트가 대역을 넣는다):
  - `async probe_doc_image(path: Path, workdir: Path, *, max_images: int, px: int, max_sections: int, page_count: int, render=None) -> ProbeResult`. 후보는 쪽이고, `max_sections` 를 넘으면 합친다. 표본은 `even_indices(쪽 수, max_images)` 쪽을 긴 변 `px` 로 줄인 JPEG 다. 표본이 아닌 후보는 `sampled=False` 다.
  - `async probe_audio(path, workdir, *, duration_sec: int, windows: int, window_sec: int, transcribe, cut, usage_context_for) -> ProbeResult`. 창의 시작 시각은 `even_indices` 로 고른다(처음·중간·끝). 후보 = 창, 위치 = `TIME 시작초~끝초`, 글 = 그 창 전사다.
  - `async probe_video(path, workdir, *, duration_sec: int, has_audio: bool, keyframes: int, windows: int, window_sec: int, px: int, transcribe, cut, grab, usage_context_for) -> ProbeResult`. 후보 = `keyframes` 개의 고른 창이고, 각 창 가운데 프레임 1장이 붙는다. STT 는 그중 `even_indices(keyframes, windows)` 창에만 한다(오디오가 없으면 하지 않는다).
  - 기본 구현: `cut(src, dst, start, sec)` 는 `ffmpeg -y -ss {start} -t {sec} -i src -vn -ac 1 -ar 16000 dst.mp3`, `grab(src, dst, at, px)` 는 `ffmpeg -y -ss {at} -i src -frames:v 1 -vf scale='if(gt(iw,ih),{px},-2)':'if(gt(iw,ih),-2,{px})' dst.jpg` 다. `transcribe(path, usage_context) -> str` 는 `audio.transcribe_detailed` 를 감싸 시각 없는 글만 준다.

- [ ] **Step 1: 실패하는 테스트 작성** — ffmpeg·whisper 를 부르지 않는다. 대역이 받은 인자를 기록한다.

```python
# api/tests/test_wb_intake_probe_media.py
"""Phase B — 미디어 훑기: 고른 간격·상한·위치. ffmpeg·STT 는 대역(유료 호출 0)."""
import asyncio
from pathlib import Path

from PIL import Image

from app.ingest.intake import probe_media


def _run(coro):
    return asyncio.run(coro)


def test_audio_windows_first_middle_last(tmp_path):
    cuts, said = [], []

    async def cut(src, dst, start, sec):
        cuts.append((start, sec)); dst.write_bytes(b"x")

    async def transcribe(path, usage_context):
        said.append(path.name); return f"말{len(said)}"

    probe = _run(probe_media.probe_audio(tmp_path / "a.m4a", tmp_path, duration_sec=600,
                                         windows=3, window_sec=20, transcribe=transcribe, cut=cut,
                                         usage_context_for=lambda i: None))
    assert [c[0] for c in cuts] == [0, 290, 580]
    assert [(c.locator.start, c.locator.end) for c in probe.candidates] == [
        ("0", "20"), ("290", "310"), ("580", "600")]
    assert [c.text for c in probe.candidates] == ["말1", "말2", "말3"]


def test_short_audio_single_window(tmp_path):
    async def cut(src, dst, start, sec): dst.write_bytes(b"x")
    async def transcribe(path, usage_context): return "짧은 말"
    probe = _run(probe_media.probe_audio(tmp_path / "a.m4a", tmp_path, duration_sec=15, windows=3,
                                         window_sec=20, transcribe=transcribe, cut=cut,
                                         usage_context_for=lambda i: None))
    assert len(probe.candidates) == 1 and probe.candidates[0].locator.end == "15"


def test_video_keyframes_and_stt_subset(tmp_path):
    grabs, cuts = [], []

    async def grab(src, dst, at, px):
        grabs.append(at); Image.new("RGB", (8, 8)).save(dst)

    async def cut(src, dst, start, sec):
        cuts.append(start); dst.write_bytes(b"x")

    async def transcribe(path, usage_context): return "말"

    probe = _run(probe_media.probe_video(tmp_path / "v.mp4", tmp_path, duration_sec=500,
                                         has_audio=True, keyframes=5, windows=3, window_sec=20,
                                         px=512, transcribe=transcribe, cut=cut, grab=grab,
                                         usage_context_for=lambda i: None))
    assert len(probe.candidates) == 5 and len(grabs) == 5
    assert len(cuts) == 3  # 처음·중간·끝 창만 STT
    assert [bool(c.text) for c in probe.candidates] == [True, False, True, False, True]
    assert all(len(c.images) == 1 for c in probe.candidates)


def test_video_without_audio_has_no_stt(tmp_path):
    async def grab(src, dst, at, px): Image.new("RGB", (8, 8)).save(dst)
    async def cut(src, dst, start, sec): raise AssertionError("오디오 없는 영상은 자르지 않는다")
    async def transcribe(path, usage_context): raise AssertionError
    probe = _run(probe_media.probe_video(tmp_path / "v.mp4", tmp_path, duration_sec=60,
                                         has_audio=False, keyframes=4, windows=3, window_sec=20,
                                         px=512, transcribe=transcribe, cut=cut, grab=grab,
                                         usage_context_for=lambda i: None))
    assert all(c.text == "" for c in probe.candidates)


def test_doc_image_samples_six_of_twenty_pages_shrunk(tmp_path):
    def render(path, index, dpi):
        return Image.new("RGB", (2000, 1000))

    probe = _run(probe_media.probe_doc_image(tmp_path / "s.pdf", tmp_path, max_images=6, px=512,
                                             max_sections=12, page_count=20, render=render))
    sampled = probe.sampled()
    assert len(probe.candidates) == 12 and len(sampled) == 6
    assert sampled[0].candidate_id == "c1" and sampled[-1].candidate_id == "c12"
    with Image.open(sampled[0].images[0]) as im:
        assert max(im.size) == 512


def test_single_image_is_one_sampled_candidate(tmp_path):
    img = tmp_path / "p.jpg"
    Image.new("RGB", (1000, 3000)).save(img)
    probe = _run(probe_media.probe_doc_image(img, tmp_path, max_images=6, px=512,
                                             max_sections=12, page_count=1))
    (c,) = probe.candidates
    assert c.sampled and c.locator.kind == "PAGE"
```

`usage_context_for(i)` 는 STT 호출 i 번째의 원장 문맥을 만든다(`segment_id=f"probe{i}"`, stage `STT`). Task 9 가 넘긴다.

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_probe_media.py` → ImportError.

- [ ] **Step 3: 구현한다.** 창 시작 시각은 `starts = [round((duration - w) * j / (k - 1)) for j in idx]` 로 정한다(`w = min(window_sec, duration)`, `k` = 창 수, 창이 하나면 `[0]`). 600초·창 3·20초이면 `[0, 290, 580]` 이다. 영상 프레임 시각은 창 가운데(`start + w // 2`)다. DOC_IMAGE 는 PDF 이면 `render(path, index, dpi)`(기본 `layout.pages._render`, dpi 72)로 쪽을 얻고, 이미지면 그 파일을 열어 `Image.thumbnail((px, px))` 로 줄인 뒤 `workdir/probe/p{n}.jpg` 로 저장한다. `page_count` 인자는 PDF 쪽 수다(호출부가 `document.pdf_page_count` 로 넘기고, 이미지면 1). 후보 묶음은 `grouping._merge` 와 같은 규칙으로 `PAGE 첫쪽~끝쪽` 을 만든다. 각 묶음의 첫 쪽이 표본 쪽이면 그 묶음이 표본이다. 표본 쪽은 `even_indices(쪽 수, max_images)` 다. 묶음이 `max_images` 보다 많으면 `even_indices(묶음 수, max_images)` 로 표본 묶음을 고르고 각 묶음의 첫 쪽을 렌더링한다. 테스트(20쪽 → 12묶음, 6표본, 첫·끝 묶음 포함)가 기준이다. 기본 `cut`·`grab` 은 `preprocess.video._run` 을 쓴다(`require_ffmpeg()` 먼저).

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_probe_media.py` → 6 passed.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 6: 분류 호출 · 프롬프트

**Files:**
- Create: `api/app/ingest/intake/classify.py`
- Create: `api/prompts/classify_intake.ko.txt`
- Test: `api/tests/test_wb_intake_classify.py`

**Interfaces:**
- Consumes: `ir.ProbeResult`, `decide.Ranked`·`IntakeClassificationError`, `providers.parse_model_spec`·`measured_generate`
- Produces:
  - 응답 스키마 `RankedLogic(logic: Literal[*LOGICS], score: float[0,1])`, `ClassifiedSection(candidate_id: str, ranking: list[RankedLogic], reason: str = "")`, `IntakeClassification(sections: list[ClassifiedSection])`
  - `ClassifyOutcome(model_sections: dict[str, list[Ranked]], raw: dict, model: str, prompt_digest: str)`
  - `render_prompt(probes: Sequence[ProbeResult], *, hints: Sequence[str], context: str | None) -> tuple[str, list[Path]]`
  - `async classify(probes: Sequence[ProbeResult], *, hints: Sequence[str], context: str | None, usage_sink, usage_context) -> ClassifyOutcome`
  - 묶음(점주 답변)에서는 후보 id 가 이미 `s{source_id}:c{n}` 처럼 자료마다 갈려 있다. 이 모듈은 id 를 그대로 쓴다.

- [ ] **Step 1: 프롬프트 파일을 쓴다** (`api/prompts/classify_intake.ko.txt`):

```text
너는 매장 업무 자료의 **용도**만 판정한다. 사실을 뽑거나 요약하지 않는다.

## 용도(로직)
- RECIPE: 메뉴 제조법. 규격별 수량·단위·제조 순서
- PROCEDURE: 오픈·마감·청소·기기 사용·발주 같은 업무 절차
- POLICY: 환불·할인·응대·금지 같은 운영 규칙
- REFERENCE: 보관 위치·비품·연락처·기기 정보 같은 매장 정보
- NOTICE: 이번 주 공지·행사·근무 변경처럼 기간이 있는 알림
- NONE: 업무와 무관(잡담·셀카·영수증 등)

## 규칙
- 아래 구간(candidate_id)마다 6개 용도 중 가능성이 있는 것을 점수(0~1)와 함께 높은 순서로 낸다.
- 애매해도 가장 가까운 용도를 1위로 둔다. 모르겠다고 비우지 않는다.
- 구간 글이 비어 있으면 첨부 그림으로 판단한다. 그림·글 모두 없으면 그 구간은 NONE 이다.
- 이유(reason)는 20자 안의 짧은 근거다.
- 입력에 있는 candidate_id 를 하나도 빠뜨리지 말고, 없는 id 를 만들지 않는다.

## 점주가 고른 종류
{hints}
참고만 한다. 내용이 다르면 내용을 따른다.

## 맥락
{context}

## 구간
{sections}
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_classify.py
"""Phase B — 분류 호출 1회. 모델은 대역, 원장 문맥 stage=CLASSIFY, 실패 시 멈춤."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest.intake import classify
from app.ingest.intake.decide import IntakeClassificationError
from app.ingest.intake.ir import Candidate, Locator, ProbeResult

PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "음료Z 샷 2"),
                                 Candidate("c2", Locator("PAGE", "2", "2"), "", sampled=False)))


def _settings(**kw):
    base = dict(intake_classifier_model="gemini:gemini-3.6-flash",
                intake_classifier_max_output_tokens=2048, ingest_mode="real")
    return NS(**{**base, **kw})


def test_prompt_lists_only_sampled_and_hints():
    prompt, images = classify.render_prompt([PROBE], hints=("RECIPE",), context=None)
    assert "c1" in prompt and "음료Z 샷 2" in prompt and "### c2" not in prompt
    # 칩은 로직 이름 그대로 "점주가 고른 종류" 칸에 들어간다
    assert "RECIPE" in prompt.split("## 점주가 고른 종류")[1].split("## 맥락")[0]
    assert images == []


def test_prompt_no_hints_says_none():
    prompt, _ = classify.render_prompt([PROBE], hints=(), context="직원 질문: 시럽 어디?")
    assert "(고르지 않음)" in prompt and "직원 질문: 시럽 어디?" in prompt


def test_images_follow_candidates(tmp_path):
    img = tmp_path / "p1.jpg"; Image.new("RGB", (4, 4)).save(img)
    probe = ProbeResult("DOC_IMAGE", (Candidate("c1", Locator("PAGE", "1", "1"), "", (img,)),))
    prompt, images = classify.render_prompt([probe], hints=(), context=None)
    assert images == [img] and "[그림 1]" in prompt


def test_classify_calls_once_with_classify_stage():
    calls = []

    async def fake_generate(spec, prompt, images, schema, **kw):
        calls.append((spec, kw["usage_context"], kw["what"]))
        return schema.model_validate({"sections": [
            {"candidate_id": "c1", "ranking": [{"logic": "RECIPE", "score": 0.9}], "reason": "표"}]})

    ctx = NS(stage="CLASSIFY")
    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", fake_generate):
        out = asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                            usage_context=ctx))
    assert len(calls) == 1 and calls[0][1] is ctx and calls[0][0].model == "gemini-3.6-flash"
    assert out.model_sections["c1"][0].logic == "RECIPE" and len(out.prompt_digest) == 16


def test_model_error_becomes_classification_error():
    async def boom(*a, **kw):
        raise RuntimeError("503")

    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", boom):
        with pytest.raises(IntakeClassificationError):
            asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                          usage_context=None))


def test_unknown_candidate_in_output_is_error():
    async def fake_generate(spec, prompt, images, schema, **kw):
        return schema.model_validate({"sections": [
            {"candidate_id": "c9", "ranking": [{"logic": "RECIPE", "score": 0.9}]}]})

    with patch.object(classify, "get_settings", lambda: _settings()), \
            patch.object(classify, "measured_generate", fake_generate):
        with pytest.raises(IntakeClassificationError):
            asyncio.run(classify.classify([PROBE], hints=(), context=None, usage_sink=None,
                                          usage_context=None))


def test_mock_build_ranks_hint_first_else_recipe():
    sections = classify.mock_sections([PROBE], hints=("POLICY",))
    assert sections == {"sections": [{"candidate_id": "c1",
                                      "ranking": [{"logic": "POLICY", "score": 0.9}],
                                      "reason": "mock"}]}
    assert classify.mock_sections([PROBE], hints=())["sections"][0]["ranking"][0]["logic"] == "RECIPE"
```

- [ ] **Step 3: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_classify.py` → ImportError.

- [ ] **Step 4: 구현한다**

```python
# api/app/ingest/intake/classify.py
"""입구 분류 호출(B-D3) — 자료(또는 답변 묶음)당 1회, 온도 0, JSON. 원장 stage=CLASSIFY.

원래 응답은 판정 기록(intake_route_decisions.model_sections)에 남긴다(계획 P9).
실패는 IntakeClassificationError 로 올린다 — 호출부가 작업을 FAILED 로 멈춘다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from app.config import get_settings
from app.ingest.intake.decide import IntakeClassificationError, Ranked
from app.ingest.intake.ir import ProbeResult
from app.ingest.providers import measured_generate, parse_model_spec

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "classify_intake.ko.txt"

Logic = Literal["RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE"]


class RankedLogic(BaseModel):
    logic: Logic
    score: float = Field(ge=0, le=1)


class ClassifiedSection(BaseModel):
    candidate_id: str
    ranking: list[RankedLogic]
    reason: str = ""


class IntakeClassification(BaseModel):
    sections: list[ClassifiedSection] = []


@dataclass(frozen=True)
class ClassifyOutcome:
    model_sections: dict[str, list[Ranked]]
    raw: dict
    model: str
    prompt_digest: str


def render_prompt(probes: Sequence[ProbeResult], *, hints: Sequence[str],
                  context: str | None) -> tuple[str, list[Path]]:
    lines, images = [], []
    for probe in probes:
        for c in probe.sampled():
            loc = c.locator
            lines.append(f"### {c.candidate_id} ({probe.normalizer} {loc.kind} {loc.start}~{loc.end})")
            for img in c.images:
                images.append(img)
                lines.append(f"[그림 {len(images)}]")
            lines.append(c.text or "(글 없음)")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (template.replace("{hints}", ", ".join(hints) if hints else "(고르지 않음)")
              .replace("{context}", context or "(없음)")
              .replace("{sections}", "\n".join(lines)))
    return prompt, images


def mock_sections(probes: Sequence[ProbeResult], *, hints: Sequence[str]) -> dict:
    """mock 모드 합성 결과 — 칩이 있으면 첫 칩, 없으면 RECIPE. 지금 mock 추출 흐름을 바꾸지 않는다."""
    logic = hints[0] if hints else "RECIPE"
    return {"sections": [{"candidate_id": c.candidate_id,
                          "ranking": [{"logic": logic, "score": 0.9}], "reason": "mock"}
                         for p in probes for c in p.sampled()]}


async def classify(probes: Sequence[ProbeResult], *, hints: Sequence[str], context: str | None,
                   usage_sink, usage_context) -> ClassifyOutcome:
    s = get_settings()
    spec = parse_model_spec(s.intake_classifier_model)
    prompt, images = render_prompt(probes, hints=hints, context=context)
    try:
        result = await measured_generate(
            spec, prompt, images, IntakeClassification, usage_sink=usage_sink,
            usage_context=usage_context, raw_sink=None,
            max_output_tokens=s.intake_classifier_max_output_tokens, what="입구 분류",
            mock_build=lambda: IntakeClassification.model_validate(
                mock_sections(probes, hints=hints)))
    except Exception as exc:
        raise IntakeClassificationError(f"분류 호출 실패: {type(exc).__name__}: {exc}") from exc
    wanted = {c.candidate_id for p in probes for c in p.sampled()}
    got = {sec.candidate_id for sec in result.sections}
    if got - wanted:
        raise IntakeClassificationError(f"입력에 없는 구간을 냈다: {sorted(got - wanted)}")
    return ClassifyOutcome(
        {sec.candidate_id: [Ranked(r.logic, r.score) for r in sec.ranking]
         for sec in result.sections},
        result.model_dump(mode="json"), spec.model,
        hashlib.sha256(prompt.encode()).hexdigest()[:16])
```

`providers/__init__.py` 의 `measured_generate` 는 Gemini 온도로 `extract_temperature`(0.0)를 쓴다. 별도 설정은 필요 없다. 누락된 표본 후보는 `decide.decide_all` 이 잡는다(Task 3).

- [ ] **Step 5: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_classify.py` → 통과.
- [ ] **Step 6: 변경을 확인한다.** `git status --short`

---

### Task 7: 기록 표 migration · 기록 함수 · 사실 `ext`

**Files:**
- Create: `supabase/migrations/20261011100000_w_intake_routing.sql`
- Create: `api/app/ingest/intake/records.py`
- Modify: `api/app/ingest/schemas.py` (`ExtractedAssertion` 에 `_ext` PrivateAttr + `ext` property)
- Modify: `api/app/ingest/pipeline.py:944-966` (`_persist_ledger` 행에 `"ext": getattr(a, "ext", None)`)
- Modify: `api/app/ingest/repository.py:279-330` (`insert_source_facts` 에 `ext` 열 `$22::jsonb`)
- Test: `api/tests/test_wb_intake_records.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) StoredRoute(decision_id: int, normalizer: str, decisions: list[SectionDecision], source: SectionDecision)` — `source` 는 `decisions` 와 함께 저장한 자료 단위 판정(`source_decision` 열)이다.
  - `async save_decision(conn, store_id: int, *, source_id: int, entry: Literal["UPLOAD","OWNER_ANSWER"], owner_answer_id: int | None, probe: ProbeResult, owner_hints: Sequence[str], outcome: ClassifyOutcome | None, decisions: Sequence[SectionDecision], source: SectionDecision, logical_call_id: str | None) -> int`. `outcome=None` 은 분류를 부르지 않은 경우(빈 후보)이고 이번에는 쓰지 않는다. 시그니처만 둔다.
  - `async latest_decision(conn, store_id: int, source_id: int) -> StoredRoute | None`
  - `async source_owner_hints(conn, store_id: int, source_id: int) -> tuple[str, ...]`
  - `async attach(conn, store_id: int, *, pending_question_id: int, source_id: int) -> bool` (새로 붙였으면 True, 이미 있으면 False)
  - `async attachments_for_question(conn, store_id: int, pending_question_id: int) -> list[int]` (source_id 오름차순)
  - `ExtractedAssertion.ext -> dict | None`, `ExtractedAssertion.set_ext(value: dict | None)`

- [ ] **Step 1: migration 을 쓴다**

```sql
-- Phase B — 입구 분류 기록·점주 답변 첨부·점주 선택 칩·사실 ext (가산 변경만).
-- 설계 W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md B-D3a·B-D6·4-3, 계획 W_PHASE_B_PLAN_20261011.md.

alter table sources add column if not exists owner_hints text[];
alter table sources drop constraint if exists sources_owner_hints_check;
alter table sources add constraint sources_owner_hints_check
  check (owner_hints is null
         or owner_hints <@ array['RECIPE','PROCEDURE','POLICY','REFERENCE','NOTICE']::text[]);

-- 로직별 확장 칸. 원장에만 둔다 — 사실 판 hash·공개 계약에 넣지 않는다(설계 4-3)
alter table source_facts add column if not exists ext jsonb;

create table if not exists intake_route_decisions (
  decision_id      bigserial primary key,
  store_id         bigint not null references stores(store_id),
  source_id        bigint not null references sources(source_id),
  entry            varchar(20) not null check (entry in ('UPLOAD', 'OWNER_ANSWER')),
  owner_answer_id  bigint references owner_answers(answer_id),
  normalizer       varchar(20) not null
                   check (normalizer in ('DOC_TEXT','DOC_IMAGE','AUDIO','VIDEO','CHAT','OWNER_TEXT')),
  -- 표본 요약만 남긴다. 원문은 저장하지 않는다(B-D6)
  sample_summary   jsonb not null,
  sample_hash      char(64) not null,
  owner_hints      text[],
  model            varchar(120),
  prompt_digest    varchar(64),
  model_sections   jsonb not null,
  decisions        jsonb not null,
  source_decision  jsonb not null,
  source_logic     varchar(20) not null
                   check (source_logic in ('RECIPE','PROCEDURE','POLICY','REFERENCE','NOTICE','NONE')),
  logical_call_id  varchar(80),
  created_at       timestamptz not null default now()
);
create index if not exists intake_route_decisions_source_idx
  on intake_route_decisions (store_id, source_id, decision_id desc);

create table if not exists owner_answer_attachments (
  store_id             bigint not null references stores(store_id),
  pending_question_id  bigint not null references pending_questions(question_id),
  source_id            bigint not null references sources(source_id),
  created_at           timestamptz not null default now(),
  primary key (store_id, source_id)
);
create index if not exists owner_answer_attachments_question_idx
  on owner_answer_attachments (store_id, pending_question_id);

create or replace function askbuddy_intake_store_check()
returns trigger language plpgsql as $$
begin
  -- 자료가 이 매장 것이어야 한다(D1)
  if not exists (select 1 from sources s where s.source_id = new.source_id and s.store_id = new.store_id) then
    raise exception '입구 기록의 자료 매장이 맞지 않는다 (store=%, source=%)', new.store_id, new.source_id;
  end if;
  if tg_table_name = 'owner_answer_attachments' then
    if not exists (select 1 from pending_questions q
                   where q.question_id = new.pending_question_id and q.store_id = new.store_id)
       or exists (select 1 from sources s where s.source_id = new.source_id and s.source_type = 'OWNER_TEXT') then
      raise exception '점주 답변 첨부의 질문 매장 또는 자료 종류가 맞지 않는다 (store=%, question=%, source=%)',
        new.store_id, new.pending_question_id, new.source_id;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists trg_intake_route_decisions_store_check on intake_route_decisions;
create trigger trg_intake_route_decisions_store_check
before insert or update on intake_route_decisions
for each row execute function askbuddy_intake_store_check();

drop trigger if exists trg_owner_answer_attachments_store_check on owner_answer_attachments;
create trigger trg_owner_answer_attachments_store_check
before insert or update on owner_answer_attachments
for each row execute function askbuddy_intake_store_check();

comment on table intake_route_decisions is '입구 분류 개발용 기록(Phase B B-D6). 제품 화면·API 없음';
comment on table owner_answer_attachments is '점주 답변 첨부 자료 — 대기 질문에 묶는다(Phase B B-D1)';
```

- [ ] **Step 2: 실패하는 테스트 작성.** SQL 실행은 Task 17 의 실제 DB 검증이 맡는다. 여기서는 기록 함수가 store_id 를 첫 인자로 넣는지, JSON 을 직렬화하는지, `ext` 가 원장 행까지 가는지를 대역 연결로 고정한다.

```python
# api/tests/test_wb_intake_records.py
"""Phase B — 판정 기록·첨부 함수(대역 연결)와 사실 ext 전달."""
import asyncio
import json

from app.ingest.intake import records
from app.ingest.intake.decide import Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.schemas import ExtractedAssertion

D = SectionDecision("c1", "RECIPE", ("RECIPE",), False, False, False, None,
                    (Ranked("RECIPE", 0.9),), (Ranked("RECIPE", 0.9),))
SRC = SectionDecision("source", "RECIPE", ("RECIPE",), False, False, False, None,
                      (Ranked("RECIPE", 0.9),), (Ranked("RECIPE", 0.9),))
PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "원문표본글"),))


class Conn:
    def __init__(self, row=None):
        self.calls, self.row = [], row

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args)); return 7

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args)); return self.row

    async def fetch(self, sql, *args):
        self.calls.append((sql, args)); return [{"source_id": 3}, {"source_id": 5}]


def test_save_decision_store_first_and_no_raw_text():
    conn = Conn()
    from types import SimpleNamespace as NS
    outcome = NS(model_sections={"c1": [Ranked("RECIPE", 0.9)]}, raw={"sections": []},
                 model="gemini-3.6-flash", prompt_digest="abcd")
    got = asyncio.run(records.save_decision(
        conn, 11, source_id=3, entry="UPLOAD", owner_answer_id=None, probe=PROBE,
        owner_hints=("RECIPE",), outcome=outcome, decisions=[D], source=SRC,
        logical_call_id="job1:src3:classify"))
    sql, args = conn.calls[0]
    assert got == 7 and args[0] == 11 and args[1] == 3 and "intake_route_decisions" in sql
    # 표본 원문은 저장하지 않는다(B-D6) — 요약·hash 만
    assert "원문표본글" not in json.dumps(args, default=str, ensure_ascii=False)


def test_latest_decision_scoped_and_parsed():
    row = {"decision_id": 7, "normalizer": "DOC_TEXT", "decisions": json.dumps([D.as_dict()]),
           "source_decision": json.dumps(SRC.as_dict())}
    conn = Conn(row)
    got = asyncio.run(records.latest_decision(conn, 11, 3))
    sql, args = conn.calls[0]
    assert "store_id = $1" in sql and args == (11, 3)
    assert got.decisions == [D] and got.source == SRC


def test_attachments_scoped():
    conn = Conn()
    assert asyncio.run(records.attachments_for_question(conn, 11, 42)) == [3, 5]
    assert "store_id = $1" in conn.calls[0][0] and conn.calls[0][1] == (11, 42)


def test_assertion_ext_round_trip_not_in_schema():
    a = ExtractedAssertion(local_ref="f1", original_assertion="x", subject="s", attribute="a",
                           value="v", confidence=0.9)
    assert a.ext is None
    a.set_ext({"timing": "OPEN"})
    assert a.ext == {"timing": "OPEN"}
    assert "ext" not in ExtractedAssertion.model_json_schema()["properties"]  # 요청 스키마 불변(D16)
```

`insert_source_facts` 에 `ext` 를 넘기는 테스트도 추가한다. 이미 `insert_source_facts` 를 대역 연결로 시험하는 테스트가 있는지 먼저 본다(`grep -rn "insert_source_facts" api/tests`). 있으면 거기에 "`ext` 키가 있으면 마지막 인자에 JSON 문자열, 없으면 None" 단언을 추가한다. 없으면 이 파일에 대역 `Conn.fetchval` 로 같은 단언을 추가한다.

- [ ] **Step 3: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_records.py` → ImportError.

- [ ] **Step 4: 구현한다.** `records.py` 의 모든 함수는 `store_id` 를 두 번째 위치 인자로 받는다. 모든 SQL 은 `where store_id = $1` 로 좁힌다. JSON 열은 `json.dumps(..., ensure_ascii=False)` 와 `$n::jsonb` 로 넣는다. `latest_decision` 은 asyncpg 가 jsonb 를 문자열로 돌려주므로 `json.loads` 한다(이미 dict 이면 그대로). `attach` 는 `insert … on conflict (store_id, source_id) do nothing returning source_id` 결과가 있으면 True 다. `schemas.ExtractedAssertion`:

```python
    # 서버가 채운다(Phase B 4-3). 로직별 확장 칸 — 원장 source_facts.ext 에만. 요청 스키마에 실리지 않는다
    _ext: dict | None = PrivateAttr(default=None)

    @property
    def ext(self) -> dict | None:
        return self._ext

    def set_ext(self, value: dict | None) -> None:
        self._ext = value
```

`repository.insert_source_facts` 의 insert 열 목록 끝에 `ext` 를, values 에 `$22::jsonb` 를 더한다. 인자는 `json.dumps(f["ext"], ensure_ascii=False) if f.get("ext") else None` 이다.

- [ ] **Step 5: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_records.py tests -k "source_facts or ledger"` → 새 테스트 통과, 회귀 없음.
- [ ] **Step 6: 격리 검사.** `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest` → 새 위반 0.
- [ ] **Step 7: 변경을 확인한다.** `git status --short`

---

### Task 8: 추출 계획 (순수 함수)

**Files:**
- Create: `api/app/ingest/intake/plan.py`
- Test: `api/tests/test_wb_intake_plan.py`

**Interfaces:**
- Consumes: `SectionDecision`, `registry.SECTIONED_NORMALIZERS`·`JOINER`
- Produces:
  - `ExtractionPlan(skip: bool, text: str | None, segments: list[tuple[str, list]] | None, notice_segment_ids: frozenset[str], hold_all_notice: bool, groups: tuple[dict, ...])`. `groups` 는 기록·로그용이고 `{"segment_id": "seg1"|None, "key": "RECIPE"|"NOTICE", "candidates": [...]}` 형태다.
  - `plan_extraction(*, normalizer: str, decisions: Sequence[SectionDecision], source: SectionDecision, sections: Mapping[str, str] | None) -> ExtractionPlan`

규칙(계획 P2):
1. 구간별(`normalizer in SECTIONED_NORMALIZERS` 이고 `sections is not None`):
   - 남길 후보 = NONE 이 아닌 판정(후보 순서). 하나도 없으면 `skip=True` 다.
   - 묶음 열쇠: NOTICE 판정이면 `"NOTICE"`, 아니면 그 판정의 `extractors` 각각이다(한 후보가 둘이면 두 묶음 모두에 들어간다). 묶음 순서는 처음 나온 순서다.
   - 묶음이 하나이면 `text = JOINER[normalizer].join(sections[c] for c in 남길 후보)`, `segments=None` 이다. 열쇠가 NOTICE 이면 `hold_all_notice=True` 다.
   - 묶음이 둘 이상이면 `segments = [(묶음 글, []) …]` 이고 id 는 `seg1..N`(파이프라인 번호 규칙)이다. NOTICE 묶음 id 는 `notice_segment_ids` 에 넣는다. `text` 는 남길 후보 전체를 이은 글이다(복구 hash 용).
   - **NONE 이 없고 묶음이 하나이면 `text` 가 전처리 결과와 같아야 한다**(Review Focus 4. Task 4 의 같은 글 보장에 기댄다).
2. 그 밖(자료 단위): `source.logic == "NONE"` 이면 `skip`, 아니면 `text=None, segments=None`(전처리 결과 그대로)이고 `hold_all_notice = source.logic == "NOTICE"` 다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_plan.py
"""Phase B — 판정 → 추출 계획. 글 자료만 구간별(2026-10-11), 나머지는 자료 단위."""
from app.ingest.intake.decide import Ranked, SectionDecision
from app.ingest.intake.plan import plan_extraction


def _d(cid, logic, extractors=None):
    ex = extractors if extractors is not None else (() if logic == "NONE" else ("RECIPE",))
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, tuple(ex), False, False, False, None, r, r)


SECTIONS = {"c1": "[1쪽]\n가", "c2": "[2쪽]\n나", "c3": "[3쪽]\n다"}


def test_nothing_dropped_same_text():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "PROCEDURE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.text == "[1쪽]\n가\n\n[2쪽]\n나\n\n[3쪽]\n다" and plan.segments is None
    assert not plan.skip and not plan.hold_all_notice


def test_none_sections_dropped():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "NONE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.text == "[1쪽]\n가\n\n[3쪽]\n다"


def test_all_none_skips():
    plan = plan_extraction(normalizer="CHAT", decisions=[_d("c1", "NONE")],
                           source=_d("source", "NONE"), sections={"c1": "x"})
    assert plan.skip


def test_notice_gets_own_segment():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "NOTICE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.segments == [("[1쪽]\n가\n\n[3쪽]\n다", []), ("[2쪽]\n나", [])]
    assert plan.notice_segment_ids == frozenset({"seg2"})


def test_only_notice_holds_all():
    plan = plan_extraction(normalizer="OWNER_TEXT", decisions=[_d("c1", "NOTICE")],
                           source=_d("source", "NOTICE"), sections={"c1": "공지"})
    assert plan.hold_all_notice and plan.text == "공지" and plan.segments is None


def test_chat_joiner_is_newline():
    plan = plan_extraction(normalizer="CHAT", decisions=[_d("c1", "RECIPE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections={"c1": "a", "c2": "b"})
    assert plan.text == "a\nb"


def test_media_is_source_level():
    plan = plan_extraction(normalizer="VIDEO", decisions=[_d("c1", "NONE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=None)
    assert plan.text is None and plan.segments is None and not plan.skip
    assert plan_extraction(normalizer="AUDIO", decisions=[_d("c1", "NONE")],
                           source=_d("source", "NONE"), sections=None).skip
    assert plan_extraction(normalizer="DOC_IMAGE", decisions=[_d("c1", "NOTICE")],
                           source=_d("source", "NOTICE"), sections=None).hold_all_notice


def test_text_normalizer_without_sections_is_source_level():
    # HYBRID 처럼 그림 쪽을 첨부하는 PDF 는 전처리가 구간 글을 주지 않는다
    plan = plan_extraction(normalizer="DOC_TEXT", decisions=[_d("c1", "NONE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=None)
    assert plan.text is None and not plan.skip


def test_two_registered_extractors_two_segments():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE", ("RECIPE", "POLICY")), _d("c2", "POLICY", ("POLICY",))],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.segments == [("[1쪽]\n가", []), ("[1쪽]\n가\n\n[2쪽]\n나", [])]
```

- [ ] **Step 2: 실패를 확인한다.** → ImportError.
- [ ] **Step 3: 구현한다** (위 규칙 그대로. 50줄 안팎. `dataclass(frozen=True)`).
- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_plan.py` → 9 passed.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 9: 업로드 파이프라인 연결 (분류 단계 · NONE · NOTICE 보류 · 재사용)

**Files:**
- Create: `api/app/ingest/intake/route.py`
- Modify: `api/app/ingest/pipeline.py` (`process_source`, `_preprocess*`, `_prepare_fact_assembly`, `_persist_fact_cards`, `PreparedAssembly`)
- Modify: `api/app/ingest/fact_cards.py:34-44` (`REASON_INTAKE_NOTICE = "INTAKE_NOTICE"`)
- Modify: `api/app/ingest/job_worker.py` (`INTAKE_NONE` 메시지)
- Test: `api/tests/test_wb_intake_pipeline.py`

**Interfaces:**
- Consumes: Task 2~8 전부
- Produces:
  - `pipeline.INTAKE_NONE = "INTAKE_NONE"` — `process_source` 반환값이다. job_worker 가 `NO_RESULT` 와 메시지 `INTAKE_NONE_MESSAGE = "업무 자료가 아니라고 판단해 추출하지 않았어요."` 로 적는다.
  - `@dataclass class IntakeCache` (route.py, 가변): `path: Path | None = None`, `pdf: PdfPages | None = None`, `docx: DocxRead | None = None`, `chat_text: str | None = None`, `sections: dict[str, str] | None = None`. `sections` 는 **전처리가 글만 냈을 때만** 전처리 핸들러가 채운다(PDF 글자 층이 있고 그림 쪽이 없으며 `pdf_input_mode` 가 TEXT·HYBRID, docx, 카톡 txt). 같은 `grouping.group_*` 결과에 `sections_text(groups, JOINER[normalizer])` 를 적용한다. `pipeline._download(pool, store_id, src, cache=None)` 은 `cache.path` 가 있으면 다시 내려받지 않고, 내려받으면 `cache.path` 에 둔다.
  - `async route.probe_source(pool, store_id: int, src, *, cache: IntakeCache, usage_sink, usage_base) -> ProbeResult`: 정규화기 판단과 훑기. 테스트·실제 DB 검증이 이 함수를 대역으로 바꾼다.
  - `async route.route_source(pool, store_id: int, src, *, cache: IntakeCache, usage_sink, usage_base: tuple | None) -> StoredRoute`: 최신 판정이 있으면 그대로 돌려준다(분류 0회). 없으면 `probe_source` → `classify.classify` → `decide_all`·`source_decision` → `records.save_decision(entry="UPLOAD")` 순서로 간다. mock 모드(`ingest_mode == "mock"`)는 `probe_source` 가 다운로드 없이 `ProbeResult("DOC_TEXT"|정규화기, (Candidate("c1", Locator("WHOLE","",""), pipeline.MOCK_PLACEHOLDER),))` 를 돌려준다. 정규화기는 `source_type` 과 확장자로 정하고, mock 의 PDF 는 DOC_TEXT 로 본다.
  - `route.full_sections(cache: IntakeCache, normalizer: str) -> dict[str, str] | None` = `cache.sections if normalizer in SECTIONED_NORMALIZERS else None`
  - pipeline 은 `from app.ingest.intake import route as intake_route` 로 들여오고 `intake_route.route_source(...)` 로 부른다(테스트가 모듈 속성을 patch 한다). route.py 는 순환 import 를 피하려고 pipeline 을 함수 안에서 들여온다.
  - `pipeline._prepare_fact_assembly(..., held_fact_ids: Mapping[int, str] | None = None)`, `PreparedAssembly` 에 마지막 필드 `held_fact_ids: frozenset[int] = frozenset()` 를 더한다(기본값이 있어야 기존 위치 인자 생성이 깨지지 않는다).
  - `fact_cards.redraft_published_card(conn, store_id, *, source_id, state, exclude_fact_ids: frozenset[int] = frozenset())`: `new_fids = await new_fact_ids_for_source(...)` 바로 뒤에서 `held_ids |= set(exclude_fact_ids)` 를 하고 `new_fids = [f for f in new_fids if f not in exclude_fact_ids]` 로 거른다. `held_ids` 에 넣어야 `defer()` 가 보류 사유(INTAKE_NOTICE)를 덮지 않는다.

**연결 순서(`process_source`):**
1. `PROCESSING` 을 적은 뒤, 지금 전처리 뒤에 있는 `CLASSIFYING` 갱신 블록을 **분류 앞**으로 옮긴다(B-D10). 작업 없는 경로(`job_id is None`)는 그대로 건너뛴다.
2. `route = await route_source(...)`. `IntakeClassificationError` 는 다른 예외처럼 `except Exception` 으로 FAILED 를 적는다(메시지에 "분류" 포함).
3. `route.source.logic == "NONE"` 이고 정규화기가 구간별이 아니면, 전처리하지 않는다. 자료 DONE, `_record_segment_failures` 는 0/1 로 적고 `INTAKE_NONE` 을 돌려준다.
4. `_preprocess(..., cache=cache)` → `plan = plan_extraction(normalizer=route.normalizer, decisions=route.decisions, source=route.source, sections=full_sections(cache, route.normalizer))`. `plan.skip` 이면 3과 같이 끝낸다. 아니면 `plan.text`·`plan.segments` 로 `text`·`segments` 를 바꾼다.
5. 원장 checkpoint 뒤, 조립 준비 전에 보류 대상을 고른다. `hold_all_notice` 이면 이 자료 원장 사실 전부, 아니면 `segment_id = any(notice_segment_ids)` 인 사실이다(`select fact_id from source_facts where store_id=$1 and source_id=$2 [and segment_id = any($3)]`). 그 fact id 들을 `{fid: REASON_INTAKE_NOTICE}` 로 `_prepare_fact_assembly(held_fact_ids=…)` 에 넘긴다.
6. `_prepare_fact_assembly`: `load_entity_groups` 결과에서 보류 사실을 빼고(사실이 0개가 된 대상의 묶음은 버린다) `HeldFact(rid, fid, eid, reason)` 을 `held` 에 더한다. 보류 사실만 가진 대상은 **REDRAFT·DEFER 판정과 상관없이** 아무 카드도 쓰지 않는다. `_persist_fact_cards` 가 그 대상을 건너뛰고(아래 7) `held` 처리로 사유를 단다.
7. `_persist_fact_cards`: 대상 루프 맨 앞에서, 그 대상의 이 자료 사실이 전부 보류이면 `continue` 한다. 일부만 보류인 대상은 `reloaded` 묶음에서도 같은 사실을 빼고 비교한다(안 그러면 STALE_INPUT 이 된다). REDRAFT 대상이면 `fact_cards.redraft_published_card` 가 고르는 새 사실에서 보류 사실을 빼야 한다. 이 함수의 사실 선택 쿼리를 읽고 `exclude_fact_ids` 인자(기본 빈 값)를 더한다. 이것은 W 파일이다.
8. 재시도·복구: `route_source` 가 최신 판정을 재사용하므로 `plan` 이 같고, 그래서 `segments` 구성도 같다. `recovery.layout_hash` 는 바뀐 `text`·`segments` 로 계산한다(지금 위치 그대로, plan 적용 뒤).

- [ ] **Step 1: 실패하는 테스트 작성.** `test_w3a_pipeline_wiring.py` 의 대역(`_ConnLease`·`_Tx`·`_planning`·`_Patches`·`_state`·`_fact`·`_worker`)을 `from tests.test_w3a_pipeline_wiring import …` 로 재사용한다(저장소에 `tests.` import 선례가 있다).

```python
# api/tests/test_wb_intake_pipeline.py
"""Phase B — process_source 의 분류 단계 연결. 모델·DB 대역(test_w3a_pipeline_wiring 방식)."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.ingest import job_worker, pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import ExtractionOutcome, PreparedAssembly
from tests.test_w3a_pipeline_wiring import _ConnLease, _planning, _Tx, _worker

SECTIONS = {"c1": "[1쪽]\n음료Z 샷 2", "c2": "[2쪽]\n잡담", "c3": "[3쪽]\n음료Z 물 225ml"}
FULL = "\n\n".join(SECTIONS.values())


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def _route(normalizer, *logics, source=None):
    decisions = [_d(f"c{i}", l) for i, l in enumerate(logics, 1)]
    return StoredRoute(1, normalizer, decisions, _d("source", source or logics[0]))


async def _run(tmp_path, *, route, sections=None, text="본문", source_type="SCAN",
               notice_fact_ids=(), route_error=None):
    """process_source 한 번(job 있음). 호출 순서를 log 로, 대역을 mocks 로 돌려준다."""
    log: list = []
    src = {"source_id": 7, "store_id": 1, "source_type": source_type,
           "file_url": "b/1/scan/x.docx", "content_hash": "h", "status": "PROCESSING"}
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)
    conn.fetch = AsyncMock(return_value=[{"fact_id": f} for f in notice_fact_ids])

    async def execute(sql, *args):
        if "CLASSIFYING" in sql:
            log.append("classifying")
    conn.execute = AsyncMock(side_effect=execute)

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    async def fake_route(pool, store_id, s, *, cache, usage_sink, usage_base):
        log.append("route")
        if route_error is not None:
            raise route_error
        return route

    async def fake_preprocess(pool, store_id, s, *, usage_sink=None, usage_context=None,
                              cache=None):
        log.append("preprocess")
        cache.sections = sections
        return text, [], []

    mocks = NS(extract=AsyncMock(return_value=ExtractionOutcome([], [], 1, 0, [], {})),
               prepare=AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning())),
               persist=AsyncMock(return_value=0), set_status=AsyncMock(), failed=AsyncMock())
    with patch.object(pipeline, "get_pool", return_value=Pool()), \
         patch.object(intake_route, "route_source", fake_route), \
         patch.object(pipeline, "_preprocess", fake_preprocess), \
         patch.object(pipeline.recovery, "load", AsyncMock(return_value=None)), \
         patch.object(pipeline.recovery, "replace", AsyncMock()), \
         patch.object(pipeline.recovery, "layout_hash", return_value="h"), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", mocks.set_status), \
         patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline, "_extract_facts_all", mocks.extract), \
         patch.object(pipeline, "_record_segment_failures", AsyncMock()), \
         patch.object(pipeline, "_prepare_fact_assembly", mocks.prepare), \
         patch.object(pipeline, "_persist_fact_cards", mocks.persist), \
         patch.object(pipeline, "_mark_failed", mocks.failed), \
         patch("app.config.get_settings", return_value=Settings(_env_file=None)):
        result = await pipeline.process_source(1, 7, job_id=3)
    return result, log, mocks


def _statuses(mocks):
    return [c.args[3] for c in mocks.set_status.await_args_list]


@pytest.mark.asyncio
async def test_classifies_once_before_preprocess_and_sets_classifying(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE"))
    assert result is None and log.count("route") == 1
    assert log.index("classifying") < log.index("route") < log.index("preprocess")
    m.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_none_skips_preprocess_and_extraction(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("VIDEO", "NONE"), source_type="VIDEO")
    assert result == pipeline.INTAKE_NONE and "preprocess" not in log
    m.extract.assert_not_awaited()
    m.prepare.assert_not_awaited()
    assert _statuses(m)[-1] == "DONE"


@pytest.mark.asyncio
async def test_text_all_none_sections_skip_after_preprocess(tmp_path):
    result, log, m = await _run(tmp_path, route=_route("CHAT", "NONE", "NONE"),
                                source_type="KAKAO", sections={"c1": "a", "c2": "b"}, text="a\nb")
    assert result == pipeline.INTAKE_NONE and "preprocess" in log
    m.extract.assert_not_awaited()
    assert _statuses(m)[-1] == "DONE"


@pytest.mark.asyncio
async def test_none_section_removed_from_extraction_text(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "NONE", "RECIPE"),
                         sections=SECTIONS, text=FULL)
    assert m.extract.await_args.kwargs["text"] == "[1쪽]\n음료Z 샷 2\n\n[3쪽]\n음료Z 물 225ml"


@pytest.mark.asyncio
async def test_unchanged_text_when_nothing_dropped(tmp_path):
    # Review Focus 4 — 거른 것이 없으면 추출 입력이 전처리 결과와 바이트 단위로 같다(D16)
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "RECIPE", "RECIPE"),
                         sections=SECTIONS, text=FULL)
    kw = m.extract.await_args.kwargs
    assert kw["text"] == FULL and kw["segments"] == []


@pytest.mark.asyncio
async def test_notice_facts_held_from_assembly(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("DOC_TEXT", "RECIPE", "NOTICE", "RECIPE"),
                         sections=SECTIONS, text=FULL, notice_fact_ids=(501, 502))
    kw = m.extract.await_args.kwargs
    assert [s[0] for s in kw["segments"]] == ["[1쪽]\n음료Z 샷 2\n\n[3쪽]\n음료Z 물 225ml",
                                              "[2쪽]\n잡담"]
    assert m.prepare.await_args.kwargs["held_fact_ids"] == {501: "INTAKE_NOTICE",
                                                            502: "INTAKE_NOTICE"}


@pytest.mark.asyncio
async def test_media_notice_holds_every_fact(tmp_path):
    _, _, m = await _run(tmp_path, route=_route("VIDEO", "NOTICE"), source_type="VIDEO",
                         notice_fact_ids=(7001,))
    assert m.prepare.await_args.kwargs["held_fact_ids"] == {7001: "INTAKE_NOTICE"}


@pytest.mark.asyncio
async def test_classification_error_marks_failed(tmp_path):
    _, log, m = await _run(tmp_path, route=None,
                           route_error=IntakeClassificationError("분류 호출 실패: JSON"))
    m.failed.assert_awaited_once()
    assert isinstance(m.failed.await_args.args[3], IntakeClassificationError)
    assert "preprocess" not in log
    m.extract.assert_not_awaited()


# ── route_source: 재사용·새 분류 ─────────────────────────────────────────

class _Pool:
    def acquire(self):
        return _ConnLease(AsyncMock())


SRC = {"source_id": 7, "store_id": 1, "source_type": "SCAN", "file_url": "b/1/scan/x.docx"}
BASE = (1, 3, "REGISTRATION", "PRODUCT", None, 42)


@pytest.mark.asyncio
async def test_route_source_reuses_latest_decision():
    # Review Focus 2 — 재시도·복구에서 분류를 다시 부르지 않는다
    stored = _route("DOC_TEXT", "RECIPE")
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=stored)), \
         patch.object(intake_route.records, "source_owner_hints", AsyncMock(return_value=())), \
         patch.object(intake_route, "probe_source", AsyncMock()) as probe, \
         patch.object(intake_route.classify, "classify", AsyncMock()) as cls:
        got = await intake_route.route_source(_Pool(), 1, SRC, cache=intake_route.IntakeCache(),
                                              usage_sink=None, usage_base=BASE)
    assert got is stored
    probe.assert_not_awaited()
    cls.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_source_classifies_and_saves_when_new():
    probe = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "글"),))
    outcome = ClassifyOutcome({"c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)]},
                              {}, "gemini-3.6-flash", "abcd")
    save = AsyncMock(return_value=42)
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=None)), \
         patch.object(intake_route.records, "source_owner_hints",
                      AsyncMock(return_value=("PROCEDURE",))), \
         patch.object(intake_route.records, "save_decision", save), \
         patch.object(intake_route, "probe_source", AsyncMock(return_value=probe)), \
         patch.object(intake_route.classify, "classify", AsyncMock(return_value=outcome)) as cls, \
         patch.object(intake_route, "get_settings", return_value=Settings(_env_file=None)):
        got = await intake_route.route_source(_Pool(), 1, SRC, cache=intake_route.IntakeCache(),
                                              usage_sink=None, usage_base=BASE)
    # 칩 가산(0.15)으로 PROCEDURE 가 1위, 미등록이라 추출기는 RECIPE
    assert got.decision_id == 42 and got.normalizer == "DOC_TEXT"
    assert got.decisions[0].logic == "PROCEDURE" and got.decisions[0].extractors == ("RECIPE",)
    assert got.decisions[0].hint_changed_decision and got.source.logic == "PROCEDURE"
    kw = save.await_args.kwargs
    assert kw["entry"] == "UPLOAD" and kw["owner_hints"] == ("PROCEDURE",)
    assert kw["logical_call_id"].endswith(":classify")
    assert cls.await_args.kwargs["usage_context"].stage == "CLASSIFY"


# ── job_worker 메시지 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_worker_maps_intake_none_message():
    # Review Focus 1
    pool, conn = _worker(linked_cards=0, pending=0)
    with patch.object(job_worker, "get_pool", return_value=pool), \
         patch.object(job_worker.pipeline, "process_source",
                      AsyncMock(return_value=pipeline.INTAKE_NONE)), \
         patch.object(job_worker, "_refresh_job", AsyncMock(return_value=("NO_RESULT", 0))), \
         patch.object(job_worker, "create_ingest_completed_notification",
                      AsyncMock(return_value=None)), \
         patch("app.config.get_settings", return_value=NS()):
        await job_worker.process_ingest_job(1, 2)
    rows = [c.args[4:] for c in conn.execute.await_args_list
            if "set status = $4, card_count = $5" in c.args[0]]
    assert rows == [("NO_RESULT", 0, "NO_RESULT", job_worker.INTAKE_NONE_MESSAGE)]
    assert job_worker.INTAKE_NONE_MESSAGE == "업무 자료가 아니라고 판단해 추출하지 않았어요."
```

```python
# api/tests/test_wb_intake_held_facts.py
"""Phase B — NOTICE 보류 사실은 조립·재초안에 들어가지 않는다(Review Focus 3)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import card_plan, fact_assembly, fact_cards, pipeline
from app.ingest.card_plan import EntityGroup
from app.ingest.fact_assembly import AssemblyInput, HeldFact
from app.ingest.fact_cards import WrittenEntity
from app.ingest.pipeline import PreparedAssembly
from tests.test_w3a_pipeline_wiring import _fact, _Patches, _persist, _planning, _Pool, _state

NOTICE = "INTAKE_NOTICE"


@pytest.mark.asyncio
async def test_prepare_removes_held_facts_and_adds_heldfact():
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 10), _fact(1, 11)))
    seen = {}

    async def plan(**kw):
        seen["revs"] = [f.fact_revision_id for g in kw["groups"] for f in g.facts]
        return _planning()

    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", plan):
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True, held_fact_ids={110: NOTICE})
    assert seen["revs"] == [10]  # _fact(1, 11) 의 fact_id 는 110
    assert HeldFact(11, 110, 1, NOTICE) in prepared.held
    assert prepared.held_fact_ids == frozenset({110})


@pytest.mark.asyncio
async def test_prepare_drops_entity_whose_facts_are_all_held():
    group = EntityGroup(entity_id=1, canonical_name="합성대상1", facts=(_fact(1, 11),))
    with patch.object(fact_assembly, "entities_for_source", AsyncMock(return_value=[1])), \
         patch.object(fact_cards, "entity_card_state", AsyncMock(return_value=_state(1, "NEW"))), \
         patch.object(fact_assembly, "load_entity_groups",
                      AsyncMock(return_value=AssemblyInput(groups=(group,), held=()))), \
         patch.object(card_plan, "check_group", lambda g: None), \
         patch.object(fact_assembly, "plan_entities", AsyncMock(return_value=_planning())) as plan:
        prepared = await pipeline._prepare_fact_assembly(
            _Pool(), 1, 7, categories=["기타"], glossary=[], usage_sink=None, usage_base=None,
            raw_sink=None, strict=True, held_fact_ids={110: NOTICE})
    assert prepared.groups == {} and plan.await_args.kwargs["groups"] == []


@pytest.mark.asyncio
async def test_entity_with_only_held_facts_writes_nothing_even_if_redraft():
    # _Patches 의 entity_fact_ids 는 [entity_id * 1000] → 대상 8 의 사실은 8000 하나
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "REDRAFT")}, groups={},
        held=(HeldFact(801, 8000, 8, NOTICE),), data_errors={}, planning=_planning(),
        held_fact_ids=frozenset({8000}))
    with _Patches(now={8: _state(8, "REDRAFT")}) as p, \
         patch.object(fact_cards, "redraft_published_card", AsyncMock()) as redraft:
        await _persist(prepared)
    redraft.assert_not_awaited()
    p.write.assert_not_awaited()
    assert ("mark", (8000,), NOTICE) in p.calls


@pytest.mark.asyncio
async def test_redraft_excludes_held_fact_ids():
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "REDRAFT")}, groups={}, held=(),
        data_errors={}, planning=_planning(), held_fact_ids=frozenset({8001}))
    written = WrittenEntity(entity_id=8, card_ids=(1,), new_version_ids=(12,), linked_fact_ids=())
    with _Patches(now={8: _state(8, "REDRAFT")}), \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[8000, 8001])), \
         patch.object(fact_cards, "redraft_published_card",
                      AsyncMock(return_value=written)) as redraft:
        created = await _persist(prepared)
    assert redraft.await_args.kwargs["exclude_fact_ids"] == frozenset({8001})
    assert created == 1


@pytest.mark.asyncio
async def test_partial_held_entity_not_stale():
    full = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=(_fact(8, 80), _fact(8, 81)))
    kept = EntityGroup(entity_id=8, canonical_name="합성대상8", facts=(_fact(8, 80),))
    prepared = PreparedAssembly(
        entity_ids=(8,), states={8: _state(8, "NEW")}, groups={8: kept}, held=(),
        data_errors={}, planning=_planning(), held_fact_ids=frozenset({810}))
    with _Patches(now={8: _state(8, "NEW")}, reload={8: full}) as p, \
         patch.object(fact_cards, "entity_fact_ids", AsyncMock(return_value=[800, 810])):
        await _persist(prepared)
    p.write.assert_awaited_once()
    assert p.write.await_args.kwargs["group"] is kept
    assert not any(isinstance(c, tuple) and c[0] == "mark" and c[2] == fact_cards.REASON_STALE_INPUT
                   for c in p.calls)
```

`_Patches.__enter__` 가 `fact_cards.entity_fact_ids` 를 먼저 patch 하므로, 위처럼 **뒤에 연** `patch.object` 가 이긴다.

`redraft_published_card` 의 `exclude_fact_ids` 동작 자체(새 사실에서 빠지고 INTAKE_NOTICE 사유가 남는다)는 실제 DB 시나리오 i-9(Task 17)가 확인한다.

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_pipeline.py tests/test_wb_intake_held_facts.py` → 실패(INTAKE_NONE·route 없음).

- [ ] **Step 3: 구현한다** — 위 "연결 순서" 1~8. `route.py` 의 정규화기 판단은 다음과 같다. SCAN·PDF 는 `document.pdf_pages(path)` 를 캐시에 두고 `has_text` 를 쓴다. 그 밖은 `capabilities.extension_of(src["file_url"] or "")` 로 확장자를 정한다. `_preprocess_scan`·`_preprocess_kakao` 는 캐시에 읽기 결과가 있으면 다시 읽지 않는다. `_preprocess_scan` 의 PDF 분기는 `cache.pdf` 를 쓰고, docx 분기는 `cache.docx` 를 쓴다. 정규화기별 훑기 호출은 다음과 같다.
  - DOC_TEXT: PDF 는 `group_pdf_pages(cache.pdf.blocks)`, docx 는 `group_docx(read)` 를 `probe_groups` 에 넣는다.
  - CHAT txt: `kakao.parse(raw, message_numbers=settings.extract_locator_hints)` 결과를 `cache.chat_text` 에 두고 `group_chat` 을 쓴다. 이렇게 해야 전처리와 같은 글이 된다. CHAT 이미지는 WHOLE 후보 하나에 그 이미지를 붙인다(`probe_doc_image` 의 이미지 경로를 쓴다).
  - DOC_IMAGE: `probe_doc_image`.
  - AUDIO·VIDEO: `audio.probe`·`video.probe` 로 길이를 얻은 뒤 `probe_audio`·`probe_video` 를 쓴다. STT 원장 문맥은 `pipeline._ctx_for(usage_base, source_id, "STT", segment_id=f"probe{i}")` 다.
  - 분류 원장 문맥: `pipeline._ctx_for(usage_base, source_id, "CLASSIFY")`.
  - 점주 칩: `records.source_owner_hints`.

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_pipeline.py tests/test_wb_intake_held_facts.py` 가 통과해야 한다. 이어서 **전체** `cd api && .venv/bin/python -m pytest -q tests` 를 돌린다. 기존 파이프라인 테스트(`test_w3a_pipeline_wiring`, `test_ingest_partial_retry`, `test_ingest_connection_release`, `test_layout_pipeline` 등)가 실패하면, 그 테스트들이 `route_source` 를 모르기 때문이다. `conftest.py` 에 자동 fixture 를 두지 않는다. 실패한 테스트 파일마다 `route_source` 대역(RECIPE 자료 단위 판정을 돌려주는 `AsyncMock`)을 명시적으로 patch 한다. 테스트의 원래 단언은 바꾸지 않는다.
- [ ] **Step 5: 격리 검사.** `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest` → 새 위반 0.
- [ ] **Step 6: 변경을 확인한다.** `git status --short`

---

### Task 10: 점주 선택 칩 — 업로드 API · 화면

**Files:**
- Modify: `api/app/ingest/schemas.py` (`CreateSourceRequest.owner_hints: list[HintLogic] = Field(default_factory=list, max_length=5)`, `HintLogic = Literal["RECIPE","PROCEDURE","POLICY","REFERENCE","NOTICE"]`)
- Modify: `api/app/ingest/repository.py` (`create_source(..., owner_hints: Sequence[str] = ())` 가 `sources.owner_hints` 에 중복 없이 저장한다. 빈 목록이면 null)
- Modify: `api/app/ingest/router.py:185-230` (`owner_hints=req.owner_hints` 전달)
- Create: `web/components/owner/intake-hint-chips.tsx`
- Modify: `web/lib/api.ts` (`registerSource` 입력에 `ownerHints?: IntakeHint[]` → `owner_hints`)
- Modify: `web/lib/ingest-submit.ts` (`submitIngest({..., hints})` 가 파일마다 같은 hints 를 보낸다. `registerOne` 을 `export async function registerFileSource(file, sourceType, token, hints)` 로 바꾸고 내부 호출부를 바꾼다)
- Modify: `web/components/owner/owner-add-composer.tsx` (찍기·파일 옆에 칩, 상태는 컴포넌트 local, 제출 뒤 초기화)
- Test: `api/tests/test_wb_owner_hints.py`

**Interfaces:**
- Produces: `IntakeHint` 타입·`INTAKE_HINT_LABELS`(web, `레시피·업무 순서·매장 규칙·매장 정보·공지`), `<IntakeHintChips value onChange disabled />`, `registerFileSource(file: File, sourceType: IngestSourceType | "TEXT", token: string, hints: IntakeHint[]): Promise<SourceCreated>` — Task 13 이 쓴다.

- [ ] **Step 1: 실패하는 API 테스트 작성**

```python
# api/tests/test_wb_owner_hints.py
"""Phase B B-D3a — 업로드 요청의 점주 선택 칩. 선택·여러 개·강제 아님·허용값만."""
import pytest
from pydantic import ValidationError

from app.ingest.schemas import CreateSourceRequest

BASE = dict(source_type="SCAN", file_url="b/1/scan/x.pdf", meta={"doc_type": "PDF"})


def test_hints_optional_default_empty():
    assert CreateSourceRequest(**BASE).owner_hints == []


def test_multiple_hints_allowed():
    assert CreateSourceRequest(**BASE, owner_hints=["RECIPE", "NOTICE"]).owner_hints == ["RECIPE", "NOTICE"]


@pytest.mark.parametrize("bad", [["NONE"], ["레시피"], ["RECIPE"] * 6])
def test_rejects_unknown_or_too_many(bad):
    with pytest.raises(ValidationError):
        CreateSourceRequest(**BASE, owner_hints=bad)
```

`repository.create_source` 에 owner_hints 가 저장되는지는 대역 연결 단언을 추가한다(`$n` 인자에 `["RECIPE","NOTICE"]`, 빈 목록이면 None). 기존 `create_source` 테스트 위치는 `grep -rn "create_source" api/tests` 로 찾는다.

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_owner_hints.py tests -k create_source`
- [ ] **Step 3: web 칩을 구현한다.** 칩은 토글 버튼 묶음이다. `aria-pressed` 를 쓰고, 터치 크기는 `components/ui` 의 기존 버튼 규격을 따른다. 위에 "이건 어떤 자료인가요? (선택, 여러 개 가능)" 문구를 둔다. 아무것도 안 골라도 제출된다. 업로드 화면 문구(G5)는 바꾸지 않는다.
- [ ] **Step 4: web 정적 검사.** `cd web && pnpm check` → 오류 0. `web-async-state-check` 스킬 절차를 수행한다(제출 mutation 에 hints 가 들어갔는지, 칩 상태가 서버 상태와 섞이지 않는지).
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 11: 점주 답변 묶음 분류 · 첨부 작업 생성

**Files:**
- Modify: `api/app/ingest/intake/route.py` (`route_owner_answer` 추가)
- Modify: `api/app/ingest/owner_text.py` (`ingest_owner_text(..., route: StoredRoute)` — NONE 이면 추출하지 않고, NOTICE 이면 원장 사실 전부를 보류한다)
- Modify: `api/app/cards/owner_answer_worker.py` (`_apply`: 첨부 조회 → 묶음 분류 → 답변 글 처리 → 첨부 작업 생성. `process_next_owner_event` 끝에서 작업을 시작한다)
- Test: `api/tests/test_wb_owner_answer_intake.py`

**Interfaces:**
- Consumes: `records.attachments_for_question`·`save_decision`·`latest_decision`, `classify.classify`, `decide.*`, `job_repository.create_job`, `job_worker.process_ingest_job`
- Produces:
  - `async route.route_owner_answer(pool, store_id: int, *, owner_answer_id: int, answer_source_id: int, question: str, answer: str, attachment_source_ids: Sequence[int], usage_sink, usage_base: tuple) -> dict[int, StoredRoute]` (source_id → 판정). 모든 자료에 판정이 이미 있으면 분류를 부르지 않는다. 일부만 있으면 **없는 자료만** 묶어 1회 분류한다. 후보 id 는 `s{source_id}:c{n}` 이다. 칩은 첨부 자료의 `owner_hints` 합집합이다. 맥락은 `"직원 질문: {question}"` 이다. 원장 문맥은 답변 자료의 `CLASSIFY` 다. 기록은 자료마다 한 행이고 `entry='OWNER_ANSWER'`, `owner_answer_id` 를 단다.
  - `async owner_answer_worker._start_attachment_job(pool, *, store_id: int, owner_user_id: int, answer_id: int, source_ids: list[int]) -> int | None`: 한 트랜잭션에서 `job_repository.find_by_idempotency(conn, store_id, key)` 를 본다. 있으면 그 job_id 를 돌려주고, 없으면 `job_repository.create_job(conn, store_id, owner_user_id, title="점주 답변 첨부", source_ids=…, category_version=stores.category_version, prompt_version="extract-cards-v1", settings={"ingest_mode": …}, idempotency_key=f"owner-answer:{answer_id}:attachments")` 의 job_id 를 돌려준다. 대상은 `UPLOADED`·`FAILED` 인 첨부만이고, 없으면 None 이다. 시작은 하지 않는다.
  - `owner_answer_worker._spawn_job(store_id: int, job_id: int) -> None`: `asyncio.create_task(job_worker.process_ingest_job(store_id, job_id))` 를 모듈 전역 `_BACKGROUND: set[asyncio.Task]` 에 넣고, 끝나면 `add_done_callback(_BACKGROUND.discard)` 로 지운다. 테스트·실제 DB 검증이 이 함수를 대역으로 바꾼다.
  - worker 는 `from app.ingest.intake import records as intake_records`, `from app.ingest.intake import route as intake_route` 로 들여오고 모듈 속성으로 부른다.
  - `owner_text.ingest_owner_text(pool, *, store_id, source_id, question, answer, run_tag, route: StoredRoute)`: `route.source.logic == "NONE"` 이면 추출을 건너뛴다(원장 0, 조립은 빈 채로 돌고 자료는 DONE). `"NOTICE"` 이면 원장 기록 뒤 `select fact_id from source_facts where store_id=$1 and source_id=$2` 전부를 `held_fact_ids={fid: REASON_INTAKE_NOTICE}` 로 `_prepare_fact_assembly` 에 넘긴다.
  - `_error_code`: `IntakeClassificationError` → `("MODEL_UNAVAILABLE", "자료 분류에 실패했습니다.")`. `MODEL_UNAVAILABLE` 은 `ERROR_TABLE` 에 있고 재시도할 수 있다. contracts 는 바꾸지 않는다.

**흐름(`_apply(pool, *, store_id, event_id, token, answer_id, jobs: list[int])`, `proposal is None` 분기):**
1. `ensure_owner_answer_source` 뒤, 짧은 연결로 `attachments = await intake_records.attachments_for_question(conn, store_id, source["question_id"])` 를 읽는다(`_load_context` 가 이미 `question_id` 를 읽는다).
2. `routes = await intake_route.route_owner_answer(pool, store_id, owner_answer_id=answer_id, answer_source_id=source_id, question=…, answer=…, attachment_source_ids=attachments, usage_sink=DbUsageSink(pool, resilient=True), usage_base=(store_id, None, "OPERATING", "PRODUCT", None, run_tag))` 를 부른다. 항상 부른다. 다 저장돼 있으면 분류 0회다.
3. 답변 글 자료가 `DONE` 이 아니면 `owner_text.ingest_owner_text(..., route=routes[source_id])` 를 부른다.
4. 결과 판정(`_read_outcome`)은 **답변 글 자료만** 본다. 지금과 같다(P8).
5. 첨부가 있으면 `job_id = await _start_attachment_job(...)` 이고, None 이 아니면 `jobs.append(job_id)` 한다. `process_next_owner_event` 는 `_apply` 가 **보고까지 끝내고 돌아온 뒤**, FAILED 가 아니면 `jobs` 마다 `_spawn_job(store_id, job_id)` 를 부른다. 작업은 `pipeline.process_source` 를 타고 저장된 판정을 재사용한다(Task 9).
6. `route_owner_answer` 안: 자료마다 `intake_records.latest_decision` 을 본다. 없는 자료만 훑는다. 답변 글은 `probe_text.probe_owner_text(question, answer)`, 첨부는 `route.probe_source(pool, store_id, src, cache=IntakeCache(), …)` 다. 훑은 결과마다 후보 id 를 `s{source_id}:{id}` 로 바꿔 `classify.classify(probes, hints=첨부 칩 합집합, context=f"직원 질문: {question}", usage_context=pipeline._ctx_for(usage_base, answer_source_id, "CLASSIFY"))` 를 1회 부른다. 결과를 자료별로 나누고 접두어를 떼어 `decide_all`·`source_decision` 을 적용한다. 자료마다 `save_decision(entry="OWNER_ANSWER", owner_answer_id=answer_id, probe=접두어 뗀 원래 probe, outcome=그 자료 몫 ClassifyOutcome)` 을 한다. **저장된 판정의 후보 id 는 접두어가 없다** — 첨부 작업의 `plan_extraction` 이 전처리 구간 id(`c1..`)와 맞춰야 하기 때문이다.

- [ ] **Step 1: 실패하는 테스트 작성.** `test_w_owner_answer_worker.WorkerTests` 의 `setUp`·`tearDown`·`_run`·`_publish_ok` 를 함수 그대로 빌려 쓴다. 상속하면 부모 테스트가 두 번 돈다.

```python
# api/tests/test_wb_owner_answer_intake.py
"""Phase B B-D1·B-U15 — 점주 답변 = 글 + 첨부 한 묶음 분류 1회, 첨부는 업로드 작업."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.cards import owner_answer_worker as worker
from app.ingest import owner_text, pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import PreparedAssembly
from tests.test_w3a_pipeline_wiring import _planning
from tests.test_w_owner_answer_worker import MOD, SOURCE, WorkerTests

ATTACH_A, ATTACH_B = 301, 302


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def _stored(logic, normalizer="OWNER_TEXT"):
    return StoredRoute(1, normalizer, [_d("c1", logic)], _d("source", logic))


class OwnerAnswerIntakeWorkerTests(unittest.IsolatedAsyncioTestCase):
    setUp_base = WorkerTests.setUp
    tearDown = WorkerTests.tearDown
    _run = WorkerTests._run
    _publish_ok = WorkerTests._publish_ok

    def setUp(self):
        self.setUp_base()
        self.attachments: list[int] = []
        self.answer_logic = "RECIPE"
        self.routed: list = []

        async def routes(pool, store_id, **kw):
            self.routed.append(kw)
            self.log.append("route")
            out = {kw["answer_source_id"]: _stored(self.answer_logic)}
            out.update({sid: _stored("RECIPE", "DOC_TEXT") for sid in kw["attachment_source_ids"]})
            return out

        extra = [
            patch(f"{MOD}.intake_records.attachments_for_question",
                  AsyncMock(side_effect=lambda *a, **k: list(self.attachments))),
            patch.object(intake_route, "route_owner_answer", side_effect=routes),
            patch(f"{MOD}._start_attachment_job", AsyncMock(return_value=77)),
            patch(f"{MOD}._spawn_job", side_effect=lambda s, j: self.log.append(f"spawn:{j}")),
        ]
        self.patches += extra
        (self.attach_rows, self.route_mock, self.start_job, self.spawn) = [p.start() for p in extra]

    async def test_text_only_answer_routes_and_extracts_without_job(self):
        with self._publish_ok():
            self.assertEqual(await self._run(), "PUBLISHED")
        (kw,) = self.routed
        self.assertEqual((kw["answer_source_id"], kw["attachment_source_ids"]), (SOURCE, []))
        self.assertEqual(self.ingest.call_args.kwargs["route"].source.logic, "RECIPE")
        self.start_job.assert_not_awaited()
        self.assertFalse(any(x.startswith("spawn") for x in self.log if isinstance(x, str)))

    async def test_attachments_go_to_one_route_call_and_job_starts_after_report(self):
        self.attachments = [ATTACH_A, ATTACH_B]
        with self._publish_ok():
            self.assertEqual(await self._run(), "PUBLISHED")
        self.assertEqual(len(self.routed), 1)
        self.assertEqual(self.routed[0]["attachment_source_ids"], [ATTACH_A, ATTACH_B])
        self.assertEqual(self.start_job.await_args.kwargs["source_ids"], [ATTACH_A, ATTACH_B])
        self.assertEqual(self.start_job.await_args.kwargs["answer_id"], 501)
        # R 완료 보고 뒤에 작업을 시작한다
        self.assertLess(self.log.index("finish:PUBLISHED"), self.log.index("spawn:77"))

    async def test_failed_answer_does_not_start_attachment_job(self):
        self.attachments = [ATTACH_A]
        self.route_mock.side_effect = IntakeClassificationError("분류 호출 실패: JSON")
        self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("MODEL_UNAVAILABLE", True))
        self.ingest.assert_not_called()
        self.assertFalse(any(isinstance(x, str) and x.startswith("spawn") for x in self.log))

    async def test_none_answer_text_reports_review_no_facts(self):
        self.answer_logic = "NONE"
        self.fact_count = 0
        self.assertEqual(await self._run(), "REVIEW")
        self.assertEqual(self.ingest.call_args.kwargs["route"].source.logic, "NONE")


# ── route_owner_answer: 묶음 1회·재사용 ────────────────────────────────────

class _Lease:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


BASE = (7, None, "OPERATING", "PRODUCT", None, 42)


def _attachment_probe(sid):
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), f"첨부{sid}"),))


class RouteOwnerAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def _route(self, *, stored: dict, hints=()):
        saves: list = []

        async def latest(conn, store_id, source_id):
            return stored.get(source_id)

        async def save(conn, store_id, **kw):
            saves.append(kw)
            return 100 + len(saves)

        async def get_source(conn, store_id, source_id):
            return {"source_id": source_id, "store_id": store_id, "source_type": "SCAN",
                    "file_url": f"b/7/scan/{source_id}.docx"}

        async def classify(probes, **kw):
            self.classify_calls.append((probes, kw))
            return ClassifyOutcome({c.candidate_id: [Ranked("RECIPE", 0.9)]
                                    for p in probes for c in p.sampled()}, {"sections": []},
                                   "gemini-3.6-flash", "abcd")

        self.classify_calls: list = []
        with patch.object(intake_route.records, "latest_decision", side_effect=latest), \
             patch.object(intake_route.records, "save_decision", side_effect=save), \
             patch.object(intake_route.records, "source_owner_hints",
                          AsyncMock(return_value=tuple(hints))), \
             patch.object(intake_route.repo, "get_source", side_effect=get_source), \
             patch.object(intake_route, "probe_source",
                          AsyncMock(side_effect=lambda pool, store_id, src, **kw:
                                    _attachment_probe(src["source_id"]))), \
             patch.object(intake_route.classify, "classify", side_effect=classify):
            routes = await intake_route.route_owner_answer(
                _Pool(), 7, owner_answer_id=501, answer_source_id=SOURCE, question="시럽 어디?",
                answer="창고 2번 선반", attachment_source_ids=[ATTACH_A, ATTACH_B],
                usage_sink=None, usage_base=BASE)
        return routes, saves

    async def test_bundle_is_one_call_with_prefixed_ids_and_three_rows(self):
        routes, saves = await self._route(stored={}, hints=("REFERENCE",))
        (probes, kw), = self.classify_calls
        ids = [c.candidate_id for p in probes for c in p.candidates]
        self.assertEqual(ids, [f"s{SOURCE}:c1", f"s{ATTACH_A}:c1", f"s{ATTACH_B}:c1"])
        self.assertEqual(kw["context"], "직원 질문: 시럽 어디?")
        self.assertEqual(kw["usage_context"].stage, "CLASSIFY")
        self.assertIn("REFERENCE", kw["hints"])
        self.assertEqual([s["entry"] for s in saves], ["OWNER_ANSWER"] * 3)
        self.assertEqual({s["owner_answer_id"] for s in saves}, {501})
        self.assertEqual(set(routes), {SOURCE, ATTACH_A, ATTACH_B})
        # 저장된 판정의 후보 id 는 접두어가 없다(첨부 작업의 구간 id 와 맞춘다)
        self.assertEqual(routes[ATTACH_A].decisions[0].candidate_id, "c1")

    async def test_all_stored_means_no_call(self):
        stored = {sid: _stored("RECIPE") for sid in (SOURCE, ATTACH_A, ATTACH_B)}
        routes, saves = await self._route(stored=stored)
        self.assertEqual(self.classify_calls, [])
        self.assertEqual(saves, [])
        self.assertIs(routes[ATTACH_B], stored[ATTACH_B])

    async def test_only_missing_sources_are_classified(self):
        routes, saves = await self._route(stored={SOURCE: _stored("RECIPE")})
        (probes, _), = self.classify_calls
        self.assertEqual([p.candidates[0].candidate_id for p in probes],
                         [f"s{ATTACH_A}:c1", f"s{ATTACH_B}:c1"])
        self.assertEqual(len(saves), 2)


# ── ingest_owner_text: NONE 건너뜀 · NOTICE 보류 ──────────────────────────

class IngestOwnerTextRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _ingest(self, logic):
        conn = AsyncMock()

        async def fetchval(sql, *args):
            if "exists" in sql:
                return False
            return 3  # category_version
        conn.fetchval = AsyncMock(side_effect=fetchval)
        conn.fetch = AsyncMock(return_value=[{"fact_id": 901}, {"fact_id": 902}])

        class Lease:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        conn.transaction = lambda: Lease()

        class Pool:
            def acquire(self):
                return Lease()

        prepare = AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning()))
        extract = AsyncMock()
        with patch.object(owner_text.repo, "glossary", AsyncMock(return_value=[])), \
             patch.object(owner_text.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
             patch.object(owner_text.repo, "set_status", AsyncMock()), \
             patch("app.ingest.extract.extract_facts", extract), \
             patch.object(pipeline, "_persist_ledger", AsyncMock(return_value={})), \
             patch.object(pipeline, "_prepare_fact_assembly", prepare), \
             patch.object(pipeline, "_persist_fact_cards", AsyncMock(return_value=0)), \
             patch.object(owner_text, "answer_fact_count", AsyncMock(return_value=0)):
            extract.return_value = type("R", (), {"assertions": [], "unresolved": []})()
            await owner_text.ingest_owner_text(Pool(), store_id=7, source_id=SOURCE,
                                               question="q", answer="a", run_tag=1,
                                               route=_stored(logic))
        return extract, prepare

    async def test_none_skips_extraction(self):
        extract, prepare = await self._ingest("NONE")
        extract.assert_not_awaited()
        self.assertFalse(prepare.await_args.kwargs.get("held_fact_ids"))

    async def test_notice_holds_every_fact_of_the_answer(self):
        extract, prepare = await self._ingest("NOTICE")
        extract.assert_awaited_once()
        self.assertEqual(prepare.await_args.kwargs["held_fact_ids"],
                         {901: "INTAKE_NOTICE", 902: "INTAKE_NOTICE"})

    async def test_recipe_extracts_without_hold(self):
        extract, prepare = await self._ingest("RECIPE")
        extract.assert_awaited_once()
        self.assertFalse(prepare.await_args.kwargs.get("held_fact_ids"))
```

route.py 는 `from app.ingest import repository as repo` 로 자료 행을 읽는다(테스트가 `intake_route.repo.get_source` 를 patch 한다).

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_owner_answer_intake.py`
- [ ] **Step 3: 구현한다** (위 흐름).
- [ ] **Step 4: 통과를 확인한다.** 새 파일과 `tests/test_w_owner_answer_worker.py tests/test_wa_owner_text.py tests/test_wa_owner_outcome.py` 가 통과해야 한다. 기존 테스트가 `route_owner_answer` 를 몰라 실패하면, Task 9 와 같은 방식으로 그 파일에서 명시적으로 patch 한다.
- [ ] **Step 5: 격리 검사.** `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards` → 새 위반 0.
- [ ] **Step 6: 변경을 확인한다.** `git status --short`

---

### Task 12: 점주 답변 첨부 API (보충 처리 포함)

**Files:**
- Modify: `api/app/ingest/router.py` (새 엔드포인트)
- Modify: `api/app/ingest/schemas.py` (`AttachOwnerAnswerRequest(source_id: int)`, `OwnerAnswerAttachment(question_id: int, source_id: int, job_id: int | None, created: bool)`)
- Test: `api/tests/test_wb_owner_answer_attach_api.py`

**Interfaces:**
- Produces: `POST /ingest/owner-answers/{question_id}/attachments` (점주만) → `OwnerAnswerAttachment`. 함수는 `async def attach_owner_answer_file(question_id: int, req: AttachOwnerAnswerRequest, background: BackgroundTasks, db: Db, claims: ApiClaims) -> OwnerAnswerAttachment` 이다. 라우터는 `from app.ingest.intake import records as intake_records` 로 들여온다.

**규칙:**
- `user_id, store_id = _job_identity(claims)` 이다(기본 `owner_only=True` → 직원은 403 `OWNER_ONLY`).
- 조회 SQL 은 셋이다. 모두 `store_id = $1` 로 좁힌다.
  - 질문: `select question_id from pending_questions where store_id = $1 and question_id = $2`
  - 자료: `select source_type from sources where store_id = $1 and source_id = $2`
  - 답변 처리 상태: `select s.status from pending_questions q join owner_answers oa on oa.question_id = q.question_id join owner_answer_sources oas on oas.store_id = q.store_id and oas.owner_answer_id = oa.answer_id join sources s on s.store_id = oas.store_id and s.source_id = oas.source_id where q.store_id = $1 and q.question_id = $2 order by oa.answer_id desc limit 1`
- 질문은 이 매장 `pending_questions` 에 있어야 하고(없으면 404 `QUESTION_NOT_FOUND`), 자료는 이 매장 것이고 `OWNER_TEXT` 가 아니어야 한다(404 `SOURCE_NOT_FOUND`·422 `INVALID_ATTACHMENT`).
- `records.attach` 를 부른다. 이미 붙어 있으면 `created=False` 이고 작업도 새로 만들지 않는다.
- **보충:** 그 질문에 답변이 있고 그 답변의 `owner_answer_sources` 자료가 이미 `DONE` 이면(= 답변 처리가 끝났으면), 첨부 하나로 `job_repository.create_job(idempotency_key=f"owner-answer-attach:{source_id}")` 를 만들고 `BackgroundTasks` 로 `process_ingest_job` 을 시작한다. 이 작업은 판정 기록이 없으므로 `process_source` 가 첨부 하나만으로 분류한다(entry `UPLOAD`. 기록 행의 owner_answer_id 는 없다).
- 답변 전이거나 처리 중이면 붙이기만 한다. 첨부는 worker 가 묶음으로 처리한다.

- [ ] **Step 1: 실패하는 테스트 작성.** `test_w_source_delete.py` 처럼 라우트 함수를 직접 부른다(가짜 DB·가짜 BackgroundTasks).

```python
# api/tests/test_wb_owner_answer_attach_api.py
"""Phase B B-D1 — 점주 답변 첨부 API. 같은 첨부 두 번 → 작업 하나(Review Focus 5)."""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.errors import ApiError
from app.ingest.router import attach_owner_answer_file
from app.ingest.schemas import AttachOwnerAnswerRequest

STORE = 5
OWNER = {"user_id": 1, "store_id": STORE, "role": "OWNER"}
R = "app.ingest.router"


class FakeDb:
    def __init__(self, *, question=True, source_type="SCAN", answer_status=None):
        self.question, self.source_type, self.answer_status = question, source_type, answer_status

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchval(self, sql, *args):
        assert args[0] == STORE, "store_id 가 첫 인자여야 한다"
        if "owner_answer_sources" in sql:
            return self.answer_status
        if "from pending_questions" in sql:
            return args[1] if self.question else None
        if "from sources" in sql:
            return self.source_type
        if "category_version" in sql:
            return 4
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        # 보충 작업 키 잠금만 쓴다(/jobs 라우트와 같은 방식)
        assert "pg_advisory_xact_lock" in sql, sql


class Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn.__name__, args))


class AttachApiTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, db, *, created=True, claims=OWNER, existing_job=None):
        bg = Background()
        with patch(f"{R}.intake_records.attach", AsyncMock(return_value=created)) as attach, \
             patch(f"{R}.job_repo.find_by_idempotency",
                   AsyncMock(return_value=existing_job)) as find, \
             patch(f"{R}.job_repo.create_job",
                   AsyncMock(return_value={"job_id": 55, "status": "QUEUED"})) as create:
            out = await attach_owner_answer_file(42, AttachOwnerAnswerRequest(source_id=9), bg,
                                                 db, claims)
        return out, bg, attach, find, create

    async def test_before_answer_only_attaches(self):
        out, bg, attach, _, create = await self._call(FakeDb())
        self.assertEqual((out.question_id, out.source_id, out.created, out.job_id), (42, 9, True, None))
        attach.assert_awaited_once()
        self.assertEqual(attach.await_args.args[1], STORE)
        self.assertEqual(attach.await_args.kwargs, {"pending_question_id": 42, "source_id": 9})
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])

    async def test_same_attachment_twice_makes_no_second_job(self):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="DONE"), created=False)
        self.assertEqual((out.created, out.job_id), (False, None))
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])

    async def test_after_answer_processed_starts_supplement_job(self):
        out, bg, _, find, create = await self._call(FakeDb(answer_status="DONE"))
        self.assertEqual(out.job_id, 55)
        self.assertEqual(find.await_args.args[1:], (STORE, "owner-answer-attach:9"))
        kw = create.await_args.kwargs
        self.assertEqual((kw["source_ids"], kw["idempotency_key"], kw["category_version"]),
                         ([9], "owner-answer-attach:9", 4))
        self.assertEqual(bg.tasks, [("process_ingest_job", (STORE, 55))])

    async def test_answer_still_processing_only_attaches(self):
        out, bg, _, _, create = await self._call(FakeDb(answer_status="PROCESSING"))
        self.assertIsNone(out.job_id)
        create.assert_not_awaited()

    async def test_existing_supplement_job_is_reused(self):
        out, bg, _, _, create = await self._call(
            FakeDb(answer_status="DONE"), existing_job={"job_id": 31, "status": "SUCCEEDED"})
        self.assertEqual(out.job_id, 31)
        create.assert_not_awaited()
        self.assertEqual(bg.tasks, [])  # QUEUED 가 아니면 다시 시작하지 않는다

    async def test_other_store_question_is_404(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(question=False))
        self.assertEqual((e.exception.status_code, e.exception.code), (404, "QUESTION_NOT_FOUND"))

    async def test_missing_source_is_404(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(source_type=None))
        self.assertEqual((e.exception.status_code, e.exception.code), (404, "SOURCE_NOT_FOUND"))

    async def test_owner_text_source_is_422(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(source_type="OWNER_TEXT"))
        self.assertEqual((e.exception.status_code, e.exception.code), (422, "INVALID_ATTACHMENT"))

    async def test_staff_is_403(self):
        with self.assertRaises(ApiError) as e:
            await self._call(FakeDb(), claims={**OWNER, "role": "STAFF"})
        self.assertEqual(e.exception.status_code, 403)
```

보충 작업 생성 순서: `find_by_idempotency(db, store_id, key)` 가 행을 돌려주면 그 job_id 를 쓰고, 그 행이 `QUEUED` 일 때만 다시 시작한다(기존 `/jobs` 라우트와 같은 규칙). 없으면 `create_job(db, store_id, user_id, title="점주 답변 첨부", source_ids=[source_id], category_version=…, prompt_version="extract-cards-v1", settings={"ingest_mode": get_settings().ingest_mode}, idempotency_key=key)` 를 부르고 `background.add_task(process_ingest_job, store_id, job_id)` 한다. 모든 쓰기는 `db.transaction()` 안이고, 키 잠금은 `/jobs` 처럼 `pg_advisory_xact_lock(hashtext($1))` 에 `f"askbuddy:ingest:{store_id}:{key}"` 를 넘긴다.
- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_owner_answer_attach_api.py`
- [ ] **Step 3: 격리 검사·`store-isolation-check` 스킬 절차.**
- [ ] **Step 4: 변경을 확인한다.** `git status --short`

---

### Task 13: 답변 화면 첨부 UI

**Files:**
- Modify: `web/components/owner/answer-question-sheet.tsx`
- Modify: `web/app/owner/questions/page.tsx` (`onSubmit` 이 첨부 완료 뒤에만 불리게)
- Modify: `web/lib/api.ts` (`attachOwnerAnswerFile(questionId: number, sourceId: number, token: string)`)
- Modify: `web/lib/query.ts` (필요하면 첨부 mutation 키)

**동작:**
- 답변 글 칸 아래에 "파일 첨부(선택)" 버튼이 있다. `acceptAttribute(caps)` 와 `sourceTypeFor` 를 그대로 쓴다. 지원하지 않는 파일과 너무 큰 파일은 고를 때 막고, 메시지는 `tooLargeMessage` 를 쓴다.
- 칩(`IntakeHintChips`)은 첨부가 있을 때만 보인다.
- 파일을 고르면 바로 `registerFileSource(file, type, token, hints)` → `attachOwnerAnswerFile` 을 순서대로 부른다. 파일마다 상태(올리는 중/완료/실패·다시 시도)를 보여 준다.
- **업로드가 하나라도 진행 중이면 제출 버튼이 꺼진다**(설계 B-D1 1차 방어). 실패한 첨부는 빼거나 다시 시도해야 제출할 수 있다.
- 답변 글은 지금처럼 필수다(R API 계약 `answer_text` 그대로).
- 서버 작업 생명주기는 화면 컴포넌트가 소유하지 않는다. 첨부 등록은 mutation 이고, 처리 결과는 작업 목록 화면이 보여 준다(`web-async-state-check` 기준).

- [ ] **Step 1: 구현한다.**
- [ ] **Step 2: 정적 검사.** `cd web && pnpm check` → 오류 0.
- [ ] **Step 3: `web-async-state-check` 스킬 절차를 수행한다.**
- [ ] **Step 4: `ui-state-walkthrough` 스킬로 합성 API 화면을 확인한다(Playwright 라우트 가로채기).** 확인 항목: 첨부 없이 제출, 첨부 업로드 중 제출 버튼 꺼짐, 첨부 실패 → 다시 시도, 첨부 완료 후 제출, 칩 선택이 `owner_hints` 로 전송됨(요청 본문 확인). 브라우저를 띄우지 못했으면 그렇게 적는다.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 14: 체크리스트 = 카드 단위

**Files:**
- Modify: `api/app/checklist/repository.py:258-276` (`load_cards`: `lines = (title,)`), `:441-449` (`record_day`: `line_no == 1` 이면 `text = title`)
- Modify: `api/app/checklist/scope.py` (주석만: "항목 = 카드 하나(제목)" — 계산은 그대로. `line_keys` 가 카드당 1개를 센다)
- Modify: `api/app/checklist/calendar.py` (`split_lines` 사용처가 없어지면 함수와 테스트를 지운다. 남으면 그대로 둔다)
- Modify: `web/components/checklist/today-screen.tsx` (카드마다 한 행: 체크박스 + 제목 링크. 제목 링크는 직원 카드 상세로 간다. 별도 카드 머리·줄 목록은 없앤다)
- Modify: `web/components/checklist/records-screen.tsx` (줄 표시 = 카드 제목. `line.title`/`line.text` 가 같으면 한 번만 보인다)
- Test: `api/tests/test_wb_checklist_card_unit.py` (신규), `api/tests/test_checklist_logic.py` (`split_lines` 를 지우면 그 테스트만 삭제), `api/scripts/verify_checklist.py` (기대 수 갱신)

**사전 확인:** 직원 카드 상세 경로를 확인한다. `web/app/staff/items/[itemId]/page.tsx` 가 받는 id 가 `card_id` 인지 읽어 본다. 아니면 직원 화면에서 카드 상세로 가는 기존 링크(`grep -rn "staff/items/" web/components`)를 따른다.

- [ ] **Step 1: 실패하는 테스트 작성.** 순수 계산(`scope.py`)은 바뀌지 않으므로 기존 `ScopeTest` 는 그대로 둔다. 바뀌는 곳은 DB 행 → 항목 변환(`load_cards`·`record_day`)이다.

```python
# api/tests/test_wb_checklist_card_unit.py
"""Phase B B-D9 — 체크 항목 = 카드 하나(제목). 본문 줄 수와 무관하다."""
import unittest
from datetime import date, datetime, timezone

from app.checklist import repository as repo
from app.checklist.scope import build_today, line_keys

STORE = 3


class FakeDb:
    def __init__(self, rows, sub=None):
        self.rows, self.sub, self.sql = rows, sub, []

    async def fetch(self, sql, *args):
        assert args[0] == STORE
        self.sql.append(sql)
        return self.rows

    async def fetchrow(self, sql, *args):
        assert args[0] == STORE
        return self.sub


def _card_row(card_id, title, content):
    return {"card_id": card_id, "card_version_id": card_id * 10, "title": title,
            "content": content, "common": True, "shift_ids": []}


class LoadCardsTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_card_is_one_item_titled(self):
        cards = await repo.load_cards(FakeDb([_card_row(1, "마감 청소", "의자 올리기\n바닥 닦기\n쓰레기"),
                                              _card_row(2, "오픈 준비", "")]), STORE)
        self.assertEqual([(c.card_id, c.lines) for c in cards],
                         [(1, ("마감 청소",)), (2, ("오픈 준비",))])  # 본문이 비어도 뜬다
        self.assertEqual(line_keys(cards), {(10, 1), (20, 1)})

    async def test_blank_title_card_is_skipped(self):
        cards = await repo.load_cards(FakeDb([_card_row(1, "  ", "본문")]), STORE)
        self.assertEqual(cards, [])


class RecordDayTest(unittest.IsolatedAsyncioTestCase):
    async def test_record_line_text_is_card_title(self):
        at = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        rows = [{"card_version_id": 10, "line_no": 1, "created_at": at, "title": "마감 청소",
                 "content": "의자 올리기\n바닥 닦기"},
                {"card_version_id": 20, "line_no": 2, "created_at": at, "title": "옛 줄 체크",
                 "content": "a\nb"}]
        out = await repo.record_day(FakeDb(rows), STORE, 7, date(2026, 10, 11))
        # 예전 줄 단위 체크(line_no 2)는 카드 단위에서 보이지 않는다
        self.assertEqual([(l["title"], l["text"]) for l in out["lines"]], [("마감 청소", "마감 청소")])


class TodayCountTest(unittest.TestCase):
    def test_remaining_is_card_count(self):
        from app.checklist.scope import ChecklistCard, Scope
        cards = [ChecklistCard(1, 10, "마감 청소", ("마감 청소",), True, frozenset()),
                 ChecklistCard(2, 20, "오픈 준비", ("오픈 준비",), True, frozenset())]
        out = build_today(business_date=date(2026, 10, 11), previous_business_date=date(2026, 10, 10),
                          previous_submitted=True, shifts=[], cards=cards, scope=Scope(True, ()),
                          checked={(10, 1)}, selected_shift_id=None, upcoming=False,
                          include_all=False, submissions=[], my_submission=None)
        self.assertEqual(out["scope_counts"], {"total": 2, "done": 1})
```

`test_checklist_logic.py` 의 `test_split_lines_drops_blank_and_trims` 는 `split_lines` 를 지우면 같이 지운다.

- [ ] **Step 2: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_checklist_card_unit.py` → `LoadCardsTest`·`RecordDayTest` 실패(지금은 본문 줄 단위)
- [ ] **Step 3: 구현한다.** API 응답 모양(`cards[].lines[]`, `line_no`, `total_lines`·`done_lines` 열 이름)은 바꾸지 않는다. 그래서 migration·web 타입 변경이 없다. 체크 키는 `(card_version_id, 1)` 이고, 같은 날 재공개되면 풀린다(P4).
- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests -k checklist`
- [ ] **Step 5: web 을 고친다 → `pnpm check` → `ui-state-walkthrough` 로 확인한다.** 오늘 할 일에 카드마다 한 행, "N개 남았어요" = 남은 카드 수, 제목을 누르면 카드 상세, 체크박스는 체크만 한다. 기록 달력 상세에 카드 제목이 나온다. 점주 현황 "체크리스트 N개" 는 카드 수다.
- [ ] **Step 6: `verify_checklist.py` 의 기대값을 카드 단위로 고친다.** 실행은 Task 17 에서 한다.
- [ ] **Step 7: 변경을 확인한다.** `git status --short`

---

### Task 15: 분류기 평가 하네스

**Files:**
- Create: `api/app/ingest/intake/evaluate.py` (지표 계산, 순수)
- Create: `api/eval/intake/README.md`, `api/eval/intake/cases.json` (합성 라벨 세트)
- Create: `api/scripts/run_intake_classifier_eval.py`
- Test: `api/tests/test_wb_intake_eval.py`

**Interfaces:**
- Produces:
  - 라벨 형식 `cases.json`: `[{"case_id": "syn-doc-text-recipe-1", "normalizer": "DOC_TEXT", "hints": [], "candidates": [{"candidate_id": "c1", "locator": {"kind":"PAGE","start":"1","end":"1"}, "text": "...", "expected": "RECIPE"}, ...]}]`. 합성 글만 넣고 이미지·음성 칸은 글 전사로 대신한다(`AUDIO`·`VIDEO` 는 전사 표본 글). 실제 자료는 `--cases <Git 제외 경로>` 로 따로 받는다.
  - `evaluate.score(cases, decisions_by_case) -> EvalReport(source_accuracy, section_accuracy, confusion: dict[str, dict[str, int]], ambiguous_ratio, per_logic_recall)`. 자료 정답은 구간 정답의 다수결(같으면 앞 구간)이고, 예측은 `source_decision.logic` 이다.
  - CLI: `python scripts/run_intake_classifier_eval.py [--cases PATH] [--real --confirm-paid] [--out PATH]`. 기본은 mock 이고, 비용 0, 하네스 배선만 확인한다. `--real` 은 `--confirm-paid` 없이는 거절한다. real 실행은 `INGEST_MODE=real`, `cost_purpose=EVALUATION` 이고, 끝에 호출 수·토큰·USD(원장 receipt 합계)를 출력한다. 결과 문서 초안은 `docs/dev/review/INTAKE_CLASSIFIER_EVAL_<날짜>.md` 형식으로 `--out` 에 쓴다.

라벨 세트는 정규화기 6 × 로직 대표 칸(각 1건 이상)과 섞인 자료 3건 이상(예: 오픈 절차 + 레시피 표 + 잡담, 구간 정답 포함)으로 만든다. 메뉴·상호는 `음료Z`·`합성매장` 같은 합성 이름만 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb_intake_eval.py
"""Phase B B-D7 — 평가 지표 계산과 하네스 안전장치. 유료 호출 0."""
import json
import subprocess
import sys
from pathlib import Path

from app.ingest.intake import evaluate
from app.ingest.intake.decide import Ranked, SectionDecision

ROOT = Path(__file__).resolve().parents[1]


def _d(cid, logic, amb=False):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, (), amb, False, False, None, r, r)


def test_score_section_and_source_accuracy_and_confusion():
    cases = [{"case_id": "a", "candidates": [{"candidate_id": "c1", "expected": "RECIPE"},
                                             {"candidate_id": "c2", "expected": "NONE"}]}]
    got = {"a": {"sections": [_d("c1", "RECIPE"), _d("c2", "RECIPE", amb=True)],
                 "source": _d("source", "RECIPE")}}
    rep = evaluate.score(cases, got)
    assert rep.section_accuracy == 0.5 and rep.source_accuracy == 1.0
    assert rep.confusion["NONE"]["RECIPE"] == 1 and rep.ambiguous_ratio == 0.5


def test_label_set_covers_every_normalizer_and_card_logic():
    cases = json.loads((ROOT / "eval/intake/cases.json").read_text(encoding="utf-8"))
    assert {c["normalizer"] for c in cases} == {"DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT"}
    labels = {x["expected"] for c in cases for x in c["candidates"]}
    assert labels == {"RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE"}
    assert sum(1 for c in cases if len({x["expected"] for x in c["candidates"]}) > 1) >= 3


def test_real_requires_confirm():
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--real"],
                         cwd=ROOT, capture_output=True, text=True)
    assert res.returncode != 0 and "--confirm-paid" in res.stderr


def test_mock_run_completes_without_cost(tmp_path):
    out = tmp_path / "eval.md"
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--out", str(out)],
                         cwd=ROOT, capture_output=True, text=True, env={"INGEST_MODE": "mock", "PATH": ""})
    assert res.returncode == 0, res.stderr
    assert "mock" in out.read_text(encoding="utf-8")
```

(`env` 에 필요한 설정이 더 있으면 `os.environ` 을 복사한 뒤 `INGEST_MODE=mock` 만 덮어쓴다.)

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_eval.py`
- [ ] **Step 3: 실제 모델 평가는 하지 않는다.** 결과 보고에 "실모델 평가: 사용자 승인 대기"라고 적는다.
- [ ] **Step 4: 변경을 확인한다.** `git status --short`

---

### Task 16: 다수결 참조 일반화

**Files:**
- Modify: `api/scripts/build_consensus_reference.py`
- Create: `api/eval/consensus/recipe_runs.json`
- Test: `api/tests/test_wb_consensus_reference.py`

**목표(설계 B-D8-4):** 이 스크립트는 레시피북 한 자료에 맞춰져 있다(`main()` 이 메뉴 101개·basestock 을 가정한다). 그래서 `main()` 의 레시피 전용 흐름은 **그대로 두고**, 재사용할 부분만 일반화한다.
1. 실행 목록(`PRIORITY`·`RUN_LABEL`·`RUN_DIRS`)을 `api/eval/consensus/recipe_runs.json` 으로 옮기고 `load_runs(path) -> tuple[list[str], dict[str, str], dict[str, str]]`(우선순위, 라벨, 폴더)로 읽는다. 모듈 전역 세 이름은 import 때 이 파일에서 채운다(기존 이름 유지).
2. `vote(groups, runs, quorum, *, key_fn=key, priority=None)` — `priority` 가 None 이면 전역 `PRIORITY` 를 쓴다. 본문의 `key(x)` 호출은 `key_fn(x)`, `PRIORITY` 는 `priority` 로 바꾼다.
3. `core_key(x)` — 공통 핵심 칸 키 `("CORE", n(attribute), value(value), unit(unit), polarity or "AFFIRM")`. 다른 로직이 시작할 자리다.
4. `KEY_FUNCS = {"RECIPE": key}`. CLI `--logic`(기본 RECIPE)를 받는다. 등록되지 않은 로직은 `SystemExit(f"{logic}: 키 함수가 없는 로직이다 — KEY_FUNCS 에 등록한 뒤 쓴다")` 로 멈춘다. RECIPE 는 지금 `main()` 을 그대로 부른다.

- [ ] **Step 1: 회귀 기준 테스트를 쓴다.**

```python
# api/tests/test_wb_consensus_reference.py
"""Phase B B-D8-4 — 다수결 참조 일반화. 같은 입력 → 같은 출력(레시피 회귀)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
SCRIPT = API / "scripts" / "build_consensus_reference.py"
GOLDEN = API / "tests" / "fixtures" / "consensus_recipe_golden.json"
RUNS = ["C2 opus", "C1 opus", "C4 sonnet"]


def _load():
    spec = importlib.util.spec_from_file_location("bcr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _f(attr, value, unit="", *, order=None, subject="음료Z"):
    return {"subject": subject, "variant": "ICE", "attribute": attr, "value": value,
            "unit": unit, "step_order": order, "polarity": "AFFIRM", "conditions": [],
            "original_assertion": f"{subject} {attr} {value}{unit}"}


def _groups():
    """같은 값 3표(샷), 2:1 로 갈린 값(물), 한 실행에만 있는 칸(토핑), 단위 철자 차이(shot)."""
    return {
        "C2 opus": [(1, _f("샷수", "2", "샷")), (1, _f("물량", "225", "ml")),
                    (1, _f("제조순서", "얼음 담기", order=1)), (2, _f("판매가", "4500", "원", subject="음료Y"))],
        "C1 opus": [(1, _f("샷수", "2", "샷")), (1, _f("물량", "220", "ml")),
                    (1, _f("제조순서", "얼음 담기", order=1)), (2, _f("판매가", "4500", "원", subject="음료Y"))],
        "C4 sonnet": [(1, _f("샷수", "2", "shot")), (1, _f("물량", "225", "ml")),
                      (1, _f("토핑", "시나몬"))],
    }


def _snapshot(module, **kw):
    agreed, contested = module.vote(_groups(), RUNS, quorum=2, **kw)
    facts = module.build_facts(agreed, "t", "syn", RUNS)
    return json.loads(json.dumps({"facts": facts, "contested": contested}, ensure_ascii=False))


def test_recipe_output_unchanged_after_refactor():
    assert _snapshot(_load()) == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_priority_argument_changes_representative():
    module = _load()
    agreed, _ = module.vote(_groups(), RUNS, quorum=2,
                            priority=["C4 sonnet", "C1 opus", "C2 opus"])
    assert {rep for (_, rep, _) in agreed.values()} == {"C4 sonnet", "C1 opus"}


def test_runs_file_keeps_old_values():
    priority, labels, dirs = _load().load_runs(API / "eval" / "consensus" / "recipe_runs.json")
    assert priority == ["C2 opus", "C1 opus", "C4 sonnet", "G3 sol", "G4 sol", "C3 sonnet"]
    assert set(labels) == set(dirs) == set(priority)


def test_core_key_uses_common_fields():
    key = _load().core_key({"attribute": "절차 단계", "value": "의자 내리기", "unit": "",
                            "polarity": "AFFIRM"})
    assert key == ("CORE", "절차단계", "의자내리기", "", "AFFIRM")


def test_unknown_logic_stops():
    res = subprocess.run([sys.executable, str(SCRIPT), "--logic", "PROCEDURE"],
                         capture_output=True, text=True)
    assert res.returncode != 0 and "키 함수" in res.stderr
```

- [ ] **Step 2: 리팩터 전 golden 을 뜬다.** 아직 `vote` 에 `priority` 인자가 없으므로 기본 호출만 쓴다.

```bash
cd api && mkdir -p tests/fixtures && .venv/bin/python -c "
import json
from tests.test_wb_consensus_reference import GOLDEN, _load, _snapshot
GOLDEN.write_text(json.dumps(_snapshot(_load()), ensure_ascii=False, indent=1), encoding='utf-8')"
```

이어서 `cd api && .venv/bin/python -m pytest -q tests/test_wb_consensus_reference.py` 를 돌린다. 기대: `test_recipe_output_unchanged_after_refactor` 만 통과하고, 나머지 4개는 실패한다(`priority` 인자·`load_runs`·`core_key`·`--logic` 없음). golden 파일이 비어 있지 않은지(`facts` 가 1건 이상인지) 눈으로 확인한다. 비어 있으면 합성 그룹이 투표를 통과하지 못한 것이므로, golden 을 고정하기 전에 `_groups()` 를 고친다.

- [ ] **Step 3: 리팩터한다.** `recipe_runs.json` 형식은 `{"logic": "RECIPE", "runs": [{"id": "C2 opus", "label": "…", "dir": "…"}, …]}` 이고, 배열 순서가 우선순위다. 값은 지금 `PRIORITY`·`RUN_LABEL`·`RUN_DIRS` 그대로 옮긴다(폴더 이름에 자료 고유명이 없음을 확인한 값이다. 결과 파일명은 여전히 코드·목록에 적지 않는다).
- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_consensus_reference.py` → 5 passed. golden 파일은 리팩터 뒤에 다시 만들지 않는다.
- [ ] **Step 5: 변경을 확인한다.** `git status --short`

---

### Task 17: 실제 DB 종단 검증 · 문서 · 최종 검사

**Files:**
- Create: `api/scripts/verify_w_intake.py`
- Modify: `api/scripts/verify_r_schema_rebuild.py` (가산: `verify_w_fact_only` 호출 **앞**에 `verify_w_intake` 호출)
- Modify: `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md` (§1 Phase B 상태, §4 B 결정 행 "확정(2026-10-11)")
- Modify: `docs/dev/plan/W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md` (끝에 "§9 계획 단계 결정(2026-10-11)" — 이 계획의 P1~P11 요약 표와 링크)
- Modify: 이 계획 파일 맨 아래 "실행 기록"

`verify_w_intake.py` 는 `verify_w_fact_only.py` 와 같은 방식이다. 합성 매장을 쓰고, 출력은 `PASS WB <id> <설명>` 이다. 대역은 네 군데다.
- **Storage 다운로드** `pipeline.storage.download`: 메모리 파일
- **분류** `classify.measured_generate`: 프롬프트의 `### <후보>` 글에서 낱말을 보고 판정한다
- **본 추출** `app.ingest.extract.extract_facts`: 입력 글에 든 열쇠 문장마다 정해 둔 사실
- **임베딩** `recorded_embeddings`

전처리·훑기·결정·기록·조립(mock)은 진짜다. 그래서 설정은 두 겹이다. `app.config.get_settings`·`pipeline.get_settings`·`intake_route.get_settings` 는 `ingest_mode="real"`(다운로드·docx 읽기·훑기가 실제로 돈다), `extract.get_settings` 는 mock 이다(조립은 mock 구현). 유료 호출은 0이다.

- [ ] **Step 1: `verify_w_intake.py` 를 쓴다.**

```python
"""실제 DB: Phase B 입구 분류 합성 종단 검증. 분류·추출·임베딩·Storage 는 대역(비용 0).

verify_r_schema_rebuild 가 부른다. 시나리오마다 새 합성 매장을 만든다.
  i-1 섞인 docx 업로드 → 판정 1행(원문 없음)·잡담 글은 추출 입력에 없음·공지 사실은 INTAKE_NOTICE·나머지 카드
  i-2 무관 자료(NONE) → 원장 0·작업 NO_RESULT + INTAKE_NONE 메시지·추출 0회
  i-3 분류 실패 → 자료 FAILED(판정 0행) → 다시 처리하면 판정 1행·DONE
  i-4 추출 실패 뒤 재처리 → 분류 다시 안 부름·판정 행 수 불변
  i-5 점주 답변 글 + 첨부 2개 → 분류 1회·판정 3행(OWNER_ANSWER)·답변 PUBLISHED·첨부 작업 1개 →
      작업 처리 때 분류 0회·첨부 카드는 공개 안 됨
  i-6 답변 처리 뒤 보충 첨부 → 작업 즉시 생성·같은 첨부 두 번이면 작업 1개
  i-7 매장 격리 — 다른 매장 질문 404·기록/첨부 표 매장 불일치 insert 는 트리거 예외
  i-8 칩 허용값 check·ext 는 원장에만(content_hash 불변)
  i-9 공개 카드 대상의 공지 사실 → 새 초안 없음·INTAKE_NOTICE
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg

from _fact_card_fixture import _mock_settings, _vectors, assertion, publish_card, seed_fact_card
from app.cards import owner_answer_worker
from app.config import get_settings
from app.errors import ApiError
from app.ingest import extract, job_worker, pipeline
from app.ingest import job_repository as job_repo
from app.ingest import repository as repo
from app.ingest.intake import classify as intake_classify
from app.ingest.intake import route as intake_route
from app.ingest.repository import fact_content_hash
from app.ingest.router import attach_owner_answer_file
from app.ingest.schemas import AttachOwnerAnswerRequest, FactExtractionResult
from app.learn.owner_delivery import submit_owner_answer
from tests.test_wb_docx import _p, _tbl
from verify_w_fact_only import _store

FILES: dict[str, bytes] = {}
CALLS = NS(classify=0, extract_texts=[])


def _checker(scenario: str):
    def check(name: str, ok: bool) -> None:
        assert ok, f"WB {scenario} {name}"
        print(f"PASS WB {scenario} {name}")
    return check


def _docx_bytes(body: str) -> bytes:
    import zipfile
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml",
                       f'<?xml version="1.0"?><w:document {ns}><w:body>{body}</w:body></w:document>')
        return path.read_bytes()


async def _download(source_id, file_url):
    from app.ingest.preprocess import storage
    path = storage.workdir(source_id) / Path(file_url).name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FILES[file_url])
    return path


def _logic_of(text: str) -> str:
    if "공지" in text:
        return "NOTICE"
    if "잡담" in text:
        return "NONE"
    if "오픈" in text:
        return "PROCEDURE"
    return "RECIPE"


def _classifier(*, fail: Exception | None = None):
    async def fake(spec, prompt, images, schema, **kw):
        if fail is not None:
            raise fail
        CALLS.classify += 1
        parts = re.split(r"^### (\S+) \(", prompt, flags=re.M)[1:]
        sections = [{"candidate_id": cid, "ranking": [{"logic": _logic_of(body), "score": 0.9}],
                     "reason": "합성"} for cid, body in zip(parts[0::2], parts[1::2])]
        return schema.model_validate({"sections": sections})
    return fake


# 입력 글에 이 열쇠 문장이 있으면 그 사실을 낸다
FACTS = {
    "의자 내리기": assertion("p1", "오픈 절차", "절차 단계", "의자 내리기"),
    "음료Z | 샷 2": assertion("r1", "음료Z", "샷", "2", unit="샷"),
    "토요일 휴무": assertion("n1", "매장", "휴무", "토요일"),
    "음료Z 할인": assertion("n2", "음료Z", "할인", "10", unit="%"),
    "음료Y 시럽": assertion("y1", "음료Y", "시럽", "1", unit="펌프"),
    "음료X | 물 200": assertion("x1", "음료X", "물", "200", unit="ml"),
    "음료W | 얼음 3": assertion("w1", "음료W", "얼음", "3", unit="개"),
}


def _extractor(*, fail: Exception | None = None):
    async def fake(*, source_id, text, **kw):
        if fail is not None:
            raise fail
        CALLS.extract_texts.append(text)
        found = [a.model_copy(update={"evidence": a.evidence.model_copy(
                     update={"source_id": source_id})})
                 for key, a in FACTS.items() if key in text]
        return FactExtractionResult(assertions=found)
    return fake


def _patches(*, classify=None, extracting=None):
    real = get_settings().model_copy(update={"ingest_mode": "real", "intake_min_section_chars": 0})
    mock = _mock_settings()
    return [
        patch("app.config.get_settings", lambda: real),
        patch.object(pipeline, "get_settings", lambda: real),
        patch.object(intake_route, "get_settings", lambda: real),
        patch.object(extract, "get_settings", lambda: mock),
        patch.object(pipeline.storage, "download", _download),
        patch.object(intake_classify, "measured_generate", classify or _classifier()),
        patch("app.ingest.extract.extract_facts", extracting or _extractor()),
        patch("app.reg.index_preparation.recorded_embeddings", _vectors),
        patch.object(job_worker, "create_ingest_completed_notification", AsyncMock()),
    ]


class _Within:
    """여러 patch 를 한 번에 연다."""

    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


async def _docx_source(db, w, body: str, *, hints=()) -> int:
    url = f"sources/{w.store}/scan/{uuid4().hex}.docx"
    FILES[url] = _docx_bytes(body)
    sid = int(await db.fetchval(
        "insert into sources (store_id, uploaded_by, source_type, title, file_url, status, "
        "owner_hints) values ($1,$2,'SCAN','합성 문서',$3,'UPLOADED',$4) returning source_id",
        w.store, w.user, url, list(hints) or None))
    await repo.create_scan(db, sid, doc_type="DOCX", doc_category=None, page_count=1)
    return sid


async def _decisions(db, store, source):
    return await db.fetch(
        "select entry, owner_answer_id, source_logic, sample_summary::text as summary, "
        "logical_call_id from intake_route_decisions where store_id=$1 and source_id=$2 "
        "order by decision_id", store, source)


async def _facts_by_subject(db, store, source):
    rows = await db.fetch(
        "select f.subject, o.disposition, o.reason from fact_occurrences o "
        "join fact_revisions r on r.store_id = o.store_id and r.fact_revision_id = o.fact_revision_id "
        "join source_facts f on f.store_id = r.store_id and f.fact_id = r.fact_id "
        "where o.store_id=$1 and o.source_id=$2", store, source)
    return {r["subject"]: (r["disposition"], r["reason"]) for r in rows}


async def _job(db, w, sources: list[int]) -> int:
    row = await job_repo.create_job(
        db, w.store, w.user, title="합성 작업", source_ids=sources,
        category_version=int(await db.fetchval(
            "select category_version from stores where store_id=$1", w.store)),
        prompt_version="extract-cards-v1", settings={"ingest_mode": "real"},
        idempotency_key=None)
    return int(row["job_id"])


MIXED = (_p("오픈 절차", "Heading1") + _p("오픈 하면 의자 내리기")
         + _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]])
         + _p("잡담", "Heading1") + _p("어제 회식 재밌었다")
         + _p("공지", "Heading1") + _p("이번 주 토요일 휴무"))


async def _scenario_i1(pool, db) -> None:
    check = _checker("i-1")
    w = await _store(db)
    sid = await _docx_source(db, w, MIXED)
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches()):
        await pipeline.process_source(w.store, sid)
    rows = await _decisions(db, w.store, sid)
    check("판정 1행·UPLOAD·원문 없음",
          len(rows) == 1 and rows[0]["entry"] == "UPLOAD" and "회식" not in rows[0]["summary"]
          and rows[0]["logical_call_id"].endswith(":classify"))
    check("분류 1회", CALLS.classify == 1)
    check("잡담 글은 추출 입력에 없다", not any("회식" in t for t in CALLS.extract_texts))
    facts = await _facts_by_subject(db, w.store, sid)
    check("공지 사실은 INTAKE_NOTICE 검수 대기",
          facts.get("매장") == ("REVIEW_PENDING", "INTAKE_NOTICE"))
    check("레시피·절차 사실은 카드로", facts.get("음료Z", ("",))[0] == "LINKED"
          and facts.get("오픈 절차", ("",))[0] == "LINKED")


async def _scenario_i2(pool, db) -> None:
    check = _checker("i-2")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("잡담", "Heading1") + _p("어제 회식 재밌었다"))
    job_id = await _job(db, w, [sid])
    CALLS.extract_texts = []
    with _Within(_patches()):
        await job_worker.process_ingest_job(w.store, job_id)
    row = await db.fetchrow("select status, error_message from ingest_job_sources "
                            "where store_id=$1 and job_id=$2", w.store, job_id)
    check("작업 NO_RESULT·메시지", row["status"] == "NO_RESULT"
          and row["error_message"] == job_worker.INTAKE_NONE_MESSAGE)
    check("추출 0회·원장 0", CALLS.extract_texts == [] and await db.fetchval(
        "select count(*) from source_facts where store_id=$1 and source_id=$2", w.store, sid) == 0)


async def _scenario_i3_i4(pool, db) -> None:
    check = _checker("i-3")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(classify=_classifier(fail=RuntimeError("합성 503")))):
        await pipeline.process_source(w.store, sid)
    status, message = await db.fetchrow(
        "select status, error_message from sources where store_id=$1 and source_id=$2", w.store, sid)
    check("분류 실패 → FAILED·판정 0행", status == "FAILED" and "분류" in (message or "")
          and len(await _decisions(db, w.store, sid)) == 0)
    with _Within(_patches()):
        await pipeline.process_source(w.store, sid)
    check("다시 처리 → 판정 1행·DONE", len(await _decisions(db, w.store, sid)) == 1
          and await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                                w.store, sid) == "DONE")

    check = _checker("i-4")
    sid = await _docx_source(db, w, _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(extracting=_extractor(fail=RuntimeError("합성 추출 실패")))):
        await pipeline.process_source(w.store, sid)
    before = len(await _decisions(db, w.store, sid))
    with _Within(_patches(classify=_classifier(fail=AssertionError("분류를 다시 부르면 안 된다")))):
        await pipeline.process_source(w.store, sid)
    check("재처리는 저장된 판정을 쓴다", before == 1
          and len(await _decisions(db, w.store, sid)) == 1
          and await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                                w.store, sid) == "DONE")


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn, args))


def _owner_claims(w):
    return {"user_id": w.user, "store_id": w.store, "role": "OWNER"}


async def _scenario_i5_i6(pool, db) -> None:
    check = _checker("i-5")
    w = await _store(db)
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,'음료Y 시럽 몇 번?','v2','synthetic-wb-i5') "
        "returning question_id", w.store, w.member)
    a1 = await _docx_source(db, w, _tbl([["음료X", "물 200"]]))
    a2 = await _docx_source(db, w, _tbl([["음료W", "얼음 3"]]))
    for sid in (a1, a2):
        out = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=sid),
                                             _Background(), db, _owner_claims(w))
        assert out.created and out.job_id is None
    reply = await submit_owner_answer(pool, store_id=w.store, member_id=w.member, question_id=qid,
                                      request_id="wb-i5-answer", answer="음료Y 시럽 1펌프",
                                      expected_revision=0)
    answer_id = int(reply["owner_answer_id"])
    spawned: list = []
    CALLS.classify = 0
    with _Within(_patches()), patch.object(owner_answer_worker, "_spawn_job",
                                           lambda s, j: spawned.append(j)):
        status = await owner_answer_worker.process_next_owner_event(pool, store_id=w.store)
    rows = await db.fetch("select source_id, entry, owner_answer_id from intake_route_decisions "
                          "where store_id=$1 and owner_answer_id=$2", w.store, answer_id)
    check("분류 1회·판정 3행 OWNER_ANSWER", CALLS.classify == 1 and len(rows) == 3
          and {r["entry"] for r in rows} == {"OWNER_ANSWER"})
    check("답변 글 결과 PUBLISHED", status == "PUBLISHED")
    job = await job_repo.find_by_idempotency(db, w.store, f"owner-answer:{answer_id}:attachments")
    check("첨부 작업 1개·시작 요청", job is not None and spawned == [int(job["job_id"])])
    with _Within(_patches()):
        await job_worker.process_ingest_job(w.store, int(job["job_id"]))
    published = await db.fetchval(
        "select count(*) from fact_occurrences o join knowledge_cards k "
        "on k.store_id = o.store_id and k.card_id = o.card_id "
        "where o.store_id=$1 and o.source_id = any($2::bigint[]) and k.published_version_id is not null",
        w.store, [a1, a2])
    check("작업은 분류를 다시 안 부르고 첨부 카드는 공개 안 됨",
          CALLS.classify == 1 and published == 0
          and len(await _facts_by_subject(db, w.store, a1)) == 1)

    check = _checker("i-6")
    a3 = await _docx_source(db, w, _tbl([["음료Z", "샷 2"]]))
    bg = _Background()
    first = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=a3), bg, db,
                                           _owner_claims(w))
    again = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=a3), bg, db,
                                           _owner_claims(w))
    jobs = await db.fetchval("select count(*) from ingest_jobs where store_id=$1 "
                             "and idempotency_key=$2", w.store, f"owner-answer-attach:{a3}")
    check("보충 첨부는 바로 작업·두 번 붙여도 작업 1개",
          first.job_id is not None and not again.created and jobs == 1 and len(bg.tasks) == 1)


async def _scenario_i7(pool, db) -> None:
    check = _checker("i-7")
    w, other = await _store(db), await _store(db)
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,'질문','v2','synthetic-wb-i7') returning question_id",
        w.store, w.member)
    foreign = await _docx_source(db, other, _p("글"))
    try:
        await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=foreign),
                                       _Background(), db, _owner_claims(other))
        rejected = False
    except ApiError as e:
        rejected = e.status_code == 404
    check("다른 매장 질문으로 첨부 → 404", rejected)
    for sql, args in [
        ("insert into owner_answer_attachments (store_id, pending_question_id, source_id) "
         "values ($1,$2,$3)", (w.store, qid, foreign)),
        ("insert into intake_route_decisions (store_id, source_id, entry, normalizer, "
         "sample_summary, sample_hash, model_sections, decisions, source_decision, source_logic) "
         "values ($1,$2,'UPLOAD','DOC_TEXT','{}',repeat('0',64),'{}','[]','{}','RECIPE')",
         (w.store, foreign)),
    ]:
        try:
            async with db.transaction():
                await db.execute(sql, *args)
            blocked = False
        except asyncpg.RaiseError:
            blocked = True
        check(f"매장 불일치 insert 차단 ({sql.split()[2]})", blocked)


async def _scenario_i8(pool, db) -> None:
    check = _checker("i-8")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("글"), hints=("RECIPE", "NOTICE"))
    check("칩 저장", await db.fetchval("select owner_hints from sources where store_id=$1 "
                                     "and source_id=$2", w.store, sid) == ["RECIPE", "NOTICE"])
    try:
        async with db.transaction():
            await db.execute("update sources set owner_hints = array['NONE'] "
                             "where store_id=$1 and source_id=$2", w.store, sid)
        refused = False
    except asyncpg.CheckViolationError:
        refused = True
    check("허용 밖 칩 거절", refused)
    a = assertion("e1", "오픈 절차", "절차 단계", "의자 내리기")
    a.set_ext({"timing": "OPEN"})
    async with db.transaction():
        await pipeline._persist_ledger(db, w.store, sid, "SCAN", [a])
    row = await db.fetchrow("select ext, content_hash from source_facts where store_id=$1 "
                            "and source_id=$2", w.store, sid)
    import json
    ext = row["ext"] if isinstance(row["ext"], dict) else json.loads(row["ext"])
    check("ext 는 원장에 그대로·content_hash 에 안 들어간다",
          ext == {"timing": "OPEN"} and row["content_hash"] == fact_content_hash(
              a.subject, a.as_variant(), a.attribute, a.value, unit=a.unit or None,
              polarity=a.polarity, conditions=list(a.conditions), exceptions=list(a.exceptions)))


async def _scenario_i9(pool, db) -> None:
    check = _checker("i-9")
    w = await _store(db)
    card_id, _ = await seed_fact_card(pool, store_id=w.store, owner_user_id=w.user,
                                      assertions=[assertion("f1", "음료Z", "샷", "2", unit="샷")])
    result = await publish_card(pool, store_id=w.store, member_id=w.member, actor_user_id=w.user,
                                card_id=card_id)
    assert result.status == "PUBLISHED", result
    versions = await db.fetchval("select count(*) from card_versions where store_id=$1 "
                                 "and card_id=$2", w.store, card_id)
    sid = await _docx_source(db, w, _p("공지", "Heading1") + _p("이번 주 음료Z 할인 공지"))
    with _Within(_patches()):
        await pipeline.process_source(w.store, sid)
    check("공개 카드 대상의 공지 사실 → 새 초안 없음",
          await db.fetchval("select count(*) from card_versions where store_id=$1 and card_id=$2",
                            w.store, card_id) == versions)
    check("그 사실은 INTAKE_NOTICE",
          (await _facts_by_subject(db, w.store, sid)).get("음료Z") == ("REVIEW_PENDING",
                                                                       "INTAKE_NOTICE"))


async def verify(pool, db) -> None:
    await _scenario_i1(pool, db)
    await _scenario_i2(pool, db)
    await _scenario_i3_i4(pool, db)
    await _scenario_i5_i6(pool, db)
    await _scenario_i7(pool, db)
    await _scenario_i8(pool, db)
    await _scenario_i9(pool, db)
    print("PASS WB all scenarios")
```

이 스크립트가 쓰는 SQL 열 이름(`ingest_job_sources.error_message`, `ingest_jobs.idempotency_key`, `fact_occurrences.card_id`)과 `_store()` 의 반환값(`user`·`store`·`member`)은 기존 검증 스크립트에서 쓰는 이름 그대로다. 실행 중 열 이름이 다르다는 오류가 나면, 그 표의 migration 을 열어 실제 이름으로 고친다. 단언의 의미는 바꾸지 않는다.

`verify_r_schema_rebuild.py` 가산(`verify_w_fact_only` 바로 앞. fact_only 의 (a) 가 DB 전체를 지우기 때문이다):

```python
            from verify_w_intake import verify as verify_w_intake
            await verify_w_intake(pool, fresh)
```
- [ ] **Step 2: 실제 DB 전체 검증을 돌린다.**

```bash
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd api && PYTHONPATH=. PYTHONUTF8=1 .venv/bin/python -B scripts/verify_r_schema_rebuild.py
docker stop askbuddy-w-verify
```

기대: 모든 migration `PASS`, 기존 검증 전부 통과, `PASS WB i-1`~`i-9` 와 `PASS WB all scenarios` 가 나와야 한다. 실패하면 멈추고 원인을 고친다(`superpowers:systematic-debugging`).

- [ ] **Step 3: 전체 단위 테스트.** `cd api && .venv/bin/python -m pytest -q tests` → 실패 0. 수는 Task 1 기준선 + 새 테스트다.
- [ ] **Step 4: 격리 검사.** `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/checklist api/app/publish` → 새 위반 0. `store-isolation-check` 스킬 절차 전체를 수행한다.
- [ ] **Step 5: web.** `cd web && pnpm check` → 오류 0. Task 10·13·14 의 화면 확인 결과를 모은다.
- [ ] **Step 6: 문서를 갱신한다.** 로드맵 상태와 설계 §9 를 쓰고, 실행 기록에 테스트 수·검증 결과·하지 않은 것(실모델 분류 평가·외부 관찰)을 사실대로 적는다.
- [ ] **Step 7: 보고하고 멈춘다.** 변경 요약과 브랜치 이름 `w/phase-b-intake` 만 보고한다. 커밋·푸시는 하지 않고, 할지 묻지도 않는다.

---

## 실행 기록

(Task 1 Step 1 에서 기준선을 적고, Task 17 에서 최종 결과를 적는다.)

| 항목 | 값 |
|---|---|
| 기준선 pytest (main 1bc2bbc) | 2186 passed, 6 skipped, 4 xfailed |
| 최종 pytest | 2348 passed, 6 skipped, 4 xfailed (2026-10-11, Task 17) |
| 최종 리뷰 수정(I1~I3) 뒤 pytest | 2367 passed, 6 skipped, 4 xfailed (2026-10-11, 새 테스트 19개) |
| 실제 DB 검증 | `verify_r_schema_rebuild.py` 통과(일회용 pgvector pg17 컨테이너, migration 51개). 새 `verify_w_intake.py` 시나리오 i-1~i-11 의 30개 확인과 `PASS WB all scenarios`. 최종 리뷰 수정 뒤 i-12(공지 보류 매장 전체 기준, 6개)·i-13(NONE 점주 재시도 덮어쓰기, 4개)를 더해 다시 통과(PASS 1104줄). i-12 는 매장 전체 보류를 끄면 실패함을 확인했다. 체크리스트 `item_id`(로드맵에 걸린 카드는 항목 id, 아니면 null) 확인 추가. 기존 W 검증 7개는 `_preprocess` 를 대역으로 바꿔 원본이 없으므로 입구 훑기·분류 대역(`scripts/_intake_stub.py`)을 더했고, 1회 삭제 리허설은 그 migration 뒤에 생기는 Phase B 표를 먼저 비운다. 평가 매장 초기화 스크립트에 Phase B 표 삭제 단계를 더했다(빠지면 자료 삭제가 FK 에 막힘) |
| 격리 검사 | `check_store_id.py api/app/ingest api/app/cards api/app/checklist api/app/publish` 새 위반 0(기존 `repository.py` 15건). 검사기 매장 표 목록에 Phase B 표 2개 추가. 합성 DB 위 API 실측: 토큰 없음 401, 직원 403, 다른 매장 질문 404, 다른 매장 자료 404, 빈 본문·허용 밖 칩 422 공통 오류 형식, 같은 첨부 두 번은 `created=false` |
| web pnpm check / 화면 확인 | `pnpm check` 오류 0(정적 검사, 테스트 아님). 화면은 합성 API Playwright: 답변 첨부(Task 13) 34개 통과, 체크리스트 카드 단위(Task 14) 40개 통과. 업로드 칩(Task 10)은 브라우저로 따로 보지 않았다 |
| 최종 리뷰 수정 web | `pnpm check` 오류 0. 답변 첨부 `duplicate` 처리·작업 화면 "그래도 추출하기" 는 브라우저로 보지 않았다 |
| 후속 1(무관 오판 자료별 그래도 추출하기) pytest | 2387 passed, 6 skipped, 4 xfailed, 188 subtests (2026-10-11, 순증 20) |
| 후속 1 실제 DB | `verify_r_schema_rebuild.py` 통과(PASS 1113줄). i-13 을 자료별 경로로 바꿈(작업 재시도는 덮지 않음·다른 매장 404·직원 403·처리 중 409, 7개), i-14 추가(섞인 SUCCEEDED 작업에서 무관 파일 하나만 다시 처리·다른 무관 파일 그대로·NEXT_RANKED, 6개) |
| 후속 1 격리·web | 격리 검사 새 위반 0(기존 15건). `pnpm check` 오류 0(정적 검사). 합성 API Playwright(`verify_wb_extract_anyway_ui.cjs`) 14개 통과 — 섞인 SUCCEEDED 작업의 무관 행에만 버튼·그 자료 경로 호출·행별 오류·처리 중 버튼 없음 |
| 유료 호출 | 0 (실모델 분류 평가·외부 앱 관찰은 사용자 승인 대기) |
