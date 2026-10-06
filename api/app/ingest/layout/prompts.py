"""레이아웃 프롬프트 파일. 코드에 지시문을 두지 않는다."""
from pathlib import Path

_DIR = Path(__file__).resolve().parents[3] / "prompts"


def render(name: str, **values: str) -> str:
    text = (_DIR / f"layout_{name}.ko.txt").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
