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
