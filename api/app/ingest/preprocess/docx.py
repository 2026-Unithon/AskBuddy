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
