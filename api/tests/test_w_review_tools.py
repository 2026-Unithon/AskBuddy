"""합성 입력만 사용한다. dev 원본/DB/외부 모델을 읽지 않는다."""
import copy
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_w_review as recovery
from annotate_w_review import annotate


def test_digest_is_order_independent():
    assert recovery.digest({"a": 1, "b": 2}) == recovery.digest({"b": 2, "a": 1})


@pytest.mark.parametrize("created,expected", [("2026-09-15T00:00:00+00:00", True),
                                               ("2026-09-14T23:59:59+00:00", False),
                                               ("2026-09-15T00:01:01+00:00", False)])
def test_run_window(created, expected):
    run = {"started_at": "2026-09-15T00:00:00+00:00", "finished_at": "2026-09-15T00:01:00+00:00"}
    assert recovery.in_window({"created_at": created}, run) is expected


def test_write_never_overwrites(tmp_path):
    path = tmp_path / "result.json"
    recovery.write_new(path, {"original": True})
    with pytest.raises(FileExistsError):
        recovery.write_new(path, {"original": False})


@pytest.fixture
def review():
    packet = {"inputs_hash": "hash", "scorer_version": "test/v1", "covered_sample": [
        {"truth": {"fact_id": "synthetic-1", "source_key": "synthetic-source"},
         "scorer": {"verdict": "COVERED"}, "human_verdict": None}], "all_undetermined": []}
    notes = {"inputs_hash": "hash", "scorer_version": "test/v1", "source_qa": "local",
             "limitations": ["AI only"], "groups": [{"ids": ["synthetic-1"], "status": "DISAGREE"}]}
    return packet, notes


def test_ai_annotation_preserves_automatic_and_human_verdict(review):
    packet, notes = review
    before = copy.deepcopy(packet)
    result = annotate(packet, notes)
    assert packet == before
    assert result["entries"][0]["scorer"]["verdict"] == "COVERED"
    assert result["entries"][0]["ai_review"]["human_verdict"] is None


@pytest.mark.parametrize("mutation", ["hash", "version", "duplicate", "outside", "missing"])
def test_annotation_rejects_wrong_packet(review, mutation):
    packet, notes = review
    if mutation == "hash":
        notes["inputs_hash"] = "wrong"
    elif mutation == "version":
        notes["scorer_version"] = "wrong"
    elif mutation == "duplicate":
        notes["groups"] *= 2
    elif mutation == "outside":
        notes["groups"][0]["ids"] = ["outside"]
    else:
        notes["groups"] = []
    with pytest.raises(ValueError):
        annotate(packet, notes)


@pytest.fixture
def retained(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "API", tmp_path)
    source = tmp_path / "eval/data/store-a/source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic original")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    run = dict(run_id=1, store_slug="eval-a", label="BASE#1", card_count=1,
               started_at="2026-09-15T00:00:00+00:00", finished_at="2026-09-15T00:01:00+00:00",
               code_version="base-dirty")
    fact = dict(fact_id="synthetic-1", subject="synthetic", variant="HOT", attribute="dose",
                value="1ml", must_have=True, source_key="synthetic-source")
    report = dict(run_id=1, store="eval-a", label="BASE#1", results=[{**fact, "verdict": "COVERED", "card_id": 1}],
                  settings={"source_hashes": {"synthetic-source": sha[:16]}})
    cards = [dict(card_id=1, title="synthetic", content="HOT dose 1ml", created_at="2026-09-15T00:00:20+00:00")]
    versions = [{**cards[0], "version_no": 1}]
    ledger = [dict(created_at="2026-09-15T00:00:20+00:00", is_superseded=False)]
    sources = [dict(content_hash=sha)]
    manifest = {"sources": [dict(source_key="synthetic-source", sha256=sha, file="source.txt")]}
    code = """from types import SimpleNamespace
def match_fact(fact, cards):
    assert fact['variant'] == 'HOT'
    return SimpleNamespace(verdict='COVERED', card_id=1)
"""
    monkeypatch.setattr(recovery.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=code))
    return run, report, cards, versions, ledger, [fact], sources, manifest


def test_retained_provenance_and_original_truth_replay(retained):
    before = copy.deepcopy(retained)
    checks, replay = recovery.validate_retained(*retained)
    assert all(checks.values())
    assert retained == before
    assert replay["dirty_checkout_unrecoverable"] is True
    assert replay["attempts"][0]["mode"] == "RECORDED_BASE_COMMIT"


@pytest.mark.parametrize("mutation,failed", [("identity", "report_identity"), ("version", "immutable_versions"),
                                          ("content", "version_content_equal"), ("corrected", "ledger_uncorrected"),
                                          ("truth", "truth_equal"), ("hash", "source_hash_equal")])
def test_retained_rejects_provenance_changes(retained, mutation, failed):
    run, report, cards, versions, ledger, truth, sources, manifest = retained
    if mutation == "identity":
        report["run_id"] = 2
    elif mutation == "version":
        versions[0]["version_no"] = 2
    elif mutation == "content":
        versions[0]["content"] = "different"
    elif mutation == "corrected":
        ledger[0]["corrected_at"] = "2026-09-15T00:00:30+00:00"
    elif mutation == "truth":
        report["results"][0]["value"] = "2ml"
    else:
        sources[0]["content_hash"] = "wrong"
    checks, _ = recovery.validate_retained(*retained)
    assert checks[failed] is False


def test_compatibility_replay_is_not_original_dirty_code(retained, monkeypatch):
    def run(cmd, **kwargs):
        verdict = "PARTIAL" if cmd[2].startswith("base:") else "COVERED"
        return SimpleNamespace(stdout=f"from types import SimpleNamespace\ndef match_fact(fact,cards):\n return SimpleNamespace(verdict='{verdict}',card_id=1)\n")
    monkeypatch.setattr(recovery.subprocess, "run", run)
    checks, replay = recovery.validate_retained(*retained, compat_code="compat")
    assert checks["committed_scorer_replay_equal"] is True
    assert len(replay["attempts"]) == 2
    assert replay["attempts"][1]["mode"] == "EXPLICIT_COMPATIBILITY_COMMIT_NOT_ORIGINAL_DIRTY_CODE"
