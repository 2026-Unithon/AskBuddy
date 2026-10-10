"""외부 앱(Claude·GPT 데스크톱) 관찰용 지시문을 조립한다.

공통 본문 `INSTRUCTION_CORE.md` 의 `{{logic.키}}`·`{{format.키}}` 자리를
로직 부록 `logic/<LOGIC>.md`·형식 부록 `format/<FORMAT>.md` 의 `## 키` 절로 채운다.
설계: docs/dev/plan/W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md B-D8.

    python3 api/scripts/build_observation_instruction.py PROCEDURE DOC_TEXT          # 표준 출력
    python3 api/scripts/build_observation_instruction.py PROCEDURE DOC_TEXT -o 지시문.md
    python3 api/scripts/build_observation_instruction.py --list
    python3 api/scripts/build_observation_instruction.py --build-all   # 지시문 30개를 지시문/ 폴더에 다시 만든다
    python3 api/scripts/build_observation_instruction.py --scaffold    # 추출결과/관찰/ 에 결과 넣을 폴더를 만든다(있는 파일은 건드리지 않음)
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "docs" / "dev" / "templates" / "extraction_observation"
BUILT_DIR = TEMPLATE_DIR / "지시문"
SCAFFOLD_DIR = ROOT / "추출결과" / "관찰"
# 폴더·파일 순서와 한글 이름표
LOGIC_ORDER = [("RECIPE", "레시피"), ("PROCEDURE", "업무절차"), ("POLICY", "운영규칙"),
               ("REFERENCE", "매장정보"), ("NOTICE", "공지일정")]
FORMAT_ORDER = [("DOC_TEXT", "문서글자"), ("DOC_IMAGE", "문서이미지"), ("AUDIO", "음성"),
                ("VIDEO", "영상"), ("CHAT", "카톡"), ("OWNER_TEXT", "점주답변")]
# 실행 폴더 이름 = run_observation.py RUN_MATRIX 의 키(모델별 1회)
RUN_IDS = ["claude-opus-5.5", "claude-sonnet-5.5", "gpt-sol-6.1", "gpt-luna-6.0"]
_PLACEHOLDER = re.compile(r"\{\{(logic|format)\.([a-z_]+)\}\}")


def logics() -> list[str]:
    return sorted(p.stem for p in (TEMPLATE_DIR / "logic").glob("*.md"))


def formats() -> list[str]:
    return sorted(p.stem for p in (TEMPLATE_DIR / "format").glob("*.md"))


def parse_sections(text: str) -> dict[str, str]:
    """`## 키` 절을 {키: 본문} 으로. 첫 `##` 앞의 글은 버린다."""
    sections: dict[str, str] = {}
    key = None
    lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^## ([a-z_]+)\s*$", line)
        if m:
            if key is not None:
                sections[key] = "\n".join(lines).strip()
            key, lines = m.group(1), []
        elif key is not None:
            lines.append(line)
    if key is not None:
        sections[key] = "\n".join(lines).strip()
    return sections


def build(logic: str, fmt: str) -> str:
    if logic not in logics():
        raise ValueError(f"모르는 로직: {logic} (있는 것: {', '.join(logics())})")
    if fmt not in formats():
        raise ValueError(f"모르는 형식: {fmt} (있는 것: {', '.join(formats())})")
    parts = {
        "logic": parse_sections((TEMPLATE_DIR / "logic" / f"{logic}.md").read_text()),
        "format": parse_sections((TEMPLATE_DIR / "format" / f"{fmt}.md").read_text()),
    }
    core = (TEMPLATE_DIR / "INSTRUCTION_CORE.md").read_text()

    def fill(m: re.Match) -> str:
        side, key = m.group(1), m.group(2)
        if key not in parts[side]:
            raise KeyError(f"{side}/{logic if side == 'logic' else fmt}.md 에 '## {key}' 절이 없다")
        return parts[side][key]

    out = _PLACEHOLDER.sub(fill, core)
    # 빈 절(규칙·점검 없음)이 남긴 빈 줄 정리
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def logic_dir_name(i: int, logic: str, label: str) -> str:
    return f"{i:02d}_{logic}_{label}"


def format_file_stem(j: int, fmt: str, label: str) -> str:
    return f"{j:02d}_{fmt}_{label}"


def built_path(logic: str, fmt: str) -> pathlib.Path:
    i = [k for k, _ in LOGIC_ORDER].index(logic) + 1
    j = [k for k, _ in FORMAT_ORDER].index(fmt) + 1
    return (BUILT_DIR / logic_dir_name(i, logic, dict(LOGIC_ORDER)[logic])
            / f"{format_file_stem(j, fmt, dict(FORMAT_ORDER)[fmt])}.md")


def build_all() -> list[pathlib.Path]:
    """로직 × 형식 지시문을 모두 만든다. 내용은 build() 와 같다(테스트가 대조)."""
    written = []
    for logic, _ in LOGIC_ORDER:
        for fmt, _ in FORMAT_ORDER:
            path = built_path(logic, fmt)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(build(logic, fmt))
            written.append(path)
    return written


_RUN_SHEET_HEAD = (
    "# 실행 기록부 — {title}\n\n"
    "> 실행기가 실행마다 한 줄 채운다. 시간·토큰은 기본 지시(CLI 시스템 프롬프트)와 기동 시간을 뺀 순수 값(자료 입력 + 지시문 + 모델 작업). 자료 이름은 익명 id 로만.\n\n"
    "자료 id: (예: proc-close-video-1)  /  원본 파일은 `원본/` 폴더에\n\n"
    "| 실행 | 도구·모델·추론 | 입력 형태 | 시작 | 순수 시간 | 결과 건수 | 호출 수 | 순수 토큰·API 환산 | 메모 |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def scaffold(root: pathlib.Path = SCAFFOLD_DIR) -> list[pathlib.Path]:
    """결과를 바로 넣을 폴더를 만든다. 이미 있는 파일은 덮지 않는다."""
    made = []

    def touch(path: pathlib.Path, text: str = "") -> None:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            made.append(path)

    # 실행 안내는 저장소 원본을 늘 그대로 복사한다(바뀌었을 때만 씀)
    guide = (TEMPLATE_DIR / "관찰_README.md").read_text()
    readme = root / "README.md"
    if not readme.exists() or readme.read_text() != guide:
        root.mkdir(parents=True, exist_ok=True)
        readme.write_text(guide)
        made.append(readme)

    for i, (logic, llabel) in enumerate(LOGIC_ORDER, 1):
        for j, (fmt, flabel) in enumerate(FORMAT_ORDER, 1):
            case = root / logic_dir_name(i, logic, llabel) / format_file_stem(j, fmt, flabel) / "자료1"
            touch(case / "지시문.md", build(logic, fmt))
            (case / "원본").mkdir(parents=True, exist_ok=True)
            rows = "".join(f"| {r} | | | | | | | | |\n" for r in RUN_IDS)
            touch(case / "RUN_SHEET.md", _RUN_SHEET_HEAD.format(title=f"{llabel} × {flabel}") + rows)
            for run in RUN_IDS:
                touch(case / run / "result.json")
                touch(case / run / "worklog.md")
                (case / run / "captures").mkdir(parents=True, exist_ok=True)
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logic", nargs="?")
    ap.add_argument("format", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--build-all", action="store_true")
    ap.add_argument("--scaffold", action="store_true")
    args = ap.parse_args(argv)
    if args.build_all or args.scaffold:
        if args.build_all:
            print(f"지시문 {len(build_all())}개 → {BUILT_DIR}")
        if args.scaffold:
            print(f"새로 만든 파일 {len(scaffold())}개 → {SCAFFOLD_DIR}")
        return 0
    if args.list or not (args.logic and args.format):
        print("로직:", ", ".join(logics()))
        print("형식:", ", ".join(formats()))
        return 0 if args.list else 2
    text = build(args.logic.upper(), args.format.upper())
    if args.out:
        pathlib.Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
