from pathlib import Path

from app.notifications import destinations as d

APP = Path(__file__).resolve().parents[1] / "app"
OLD = ("/owner/questions/v2", "/staff/chat", "/owner/cards/review", "/staff/roadmap", "/owner/upload", "/owner/dashboard")


def test_owner_question():
    assert d.owner_question(101) == "/owner/questions/101"


def test_owner_job_cards():
    assert d.owner_job_cards(7) == "/owner/cards?status=all&job_id=7"


def test_staff_session_quotes_and_falls_back():
    assert d.staff_session("a b/c") == "/staff/ask?session_id=a%20b%2Fc"
    assert d.staff_session(None) == "/staff/ask"
    assert d.staff_session("") == "/staff/ask"


def test_no_old_destination_left_in_app():
    hits = [
        f"{path.relative_to(APP)}:{no}"
        for path in APP.rglob("*.py")
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(f'"{old}' in line or f"'{old}" in line for old in OLD)
    ]
    assert hits == []
