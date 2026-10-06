"""레이아웃 경로의 자료형.

모델 출력 스키마는 기본값 없이 모든 필드가 필수다. additionalProperties 는 넣지 않는다 —
Gemini response_schema 가 그 키를 거절한다(실호출 400). Anthropic 으로 보낼 때만
providers.anthropic_call.strict_schema 가 모든 object 에 additionalProperties:false 를 붙인다.
좌표: 모델은 0~1 정규화, 코드는 원본 px 정수 `Box=(x0, y0, x1, y1)`.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Box = tuple[int, int, int, int]


class _Strict(BaseModel):
    """모든 필드 필수(기본값 없음). 공급자별 엄격화는 호출부가 한다."""


class TableInfo(_Strict):
    header_columns: list[str]
    expected_rows: int | None
    row_label_column: int | None


class Region(_Strict):
    kind: Literal["TABLE", "PROSE", "FORM", "PHOTO", "FOOTNOTE"]
    bbox: list[float]          # [x0, y0, x1, y1] 0~1
    reading_order: int
    table: TableInfo | None


class RegionMap(_Strict):
    regions: list[Region]


class BandRow(_Strict):
    row_label: str | None
    cells: list[str]
    cut_top: bool
    cut_bottom: bool


class BandRows(_Strict):
    rows: list[BandRow]


class ProseLines(_Strict):
    lines: list[str]


class CropRequest(_Strict):
    bbox: list[float]          # 구역 안 0~1
    scale: float


class CellAnswer(_Strict):
    cell_id: str
    value: str | None
    unreadable_reason: str | None


class RecheckTurn(_Strict):
    crops: list[CropRequest]
    answers: list[CellAnswer]


class LayoutFact(_Strict):
    row_ref: str               # 행 라벨 또는 '행N'
    original_assertion: str
    subject: str
    variant: str
    attribute: str
    value: str
    unit: str
    polarity: Literal["AFFIRM", "NEGATE"]
    conditions: list[str]
    exceptions: list[str]
    order: int


class ExpandResult(_Strict):
    facts: list[LayoutFact]


class GroupSpan(_Strict):
    column_index: int          # 머리글 기준 0부터
    label: str                 # 합쳐진 칸의 글 그대로(세로쓰기면 이어 붙여 한 줄로)
    first_row: str             # 범위 첫 행의 행 번호(표에 보이는 그대로)
    last_row: str              # 범위 마지막 행의 행 번호


class GroupSpans(_Strict):
    spans: list[GroupSpan]


@dataclass
class PageImage:
    number: int
    path: Path
    width: int
    height: int


@dataclass
class PlacedRegion:
    page: int
    region_id: str             # p{쪽}-r{순번}
    kind: str                  # Region.kind 또는 UNCLASSIFIED
    box: Box
    order: int
    table: TableInfo | None
    added_by: Literal["MODEL", "COVERAGE", "FALLBACK"]


@dataclass
class TranscribedRow:
    label: str | None
    cells: list[str]
    band_index: int
    cut_top: bool = False
    cut_bottom: bool = False


@dataclass
class CellFlag:
    cell_id: str               # {region_id}:{row_index}:{col} 또는 {region_id}:{row_index}:row
    row_index: int
    col: int | None            # None 이면 행 단위 문제
    reason: Literal["OVERLAP_MISMATCH", "COLUMN_COUNT", "ROW_MISSING", "ROW_COUNT"]
    band_index: int


@dataclass
class TableResult:
    region: PlacedRegion
    header: list[str]
    rows: list[TranscribedRow]
    flags: list[CellFlag]
    band_boxes: list[Box]
    rerouted: bool = False
    unreadable: dict[tuple[int, int], str] = field(default_factory=dict)  # (row, col) → 사유
    group_columns: set[int] = field(default_factory=set)         # 세로 병합 라벨로 덮은 열
    group_cells: set[tuple[int, int]] = field(default_factory=set)  # 덮은 (행, 열)
    group_rows: int = 0                                          # 덮은 행 수


@dataclass
class ProseResult:
    region: PlacedRegion
    lines: list[str]


@dataclass
class Caps:
    bands_left: int
    recheck_calls_left: int
