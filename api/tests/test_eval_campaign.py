from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.team.eval_campaign import (
    CampaignError,
    append_campaign_event,
    claim_campaign_run,
    enforce_observed_budget,
    sha256_bytes,
    validate_campaign,
)


MANIFEST = b'{"split":"holdout"}'
SETTINGS = {
    "scorer_version": "w-scorer/v3",
    "code_version": "abc123def456",
    "extract_prompt_version": "extract@1",
    "assemble_prompt_version": "assemble@1",
    "extraction_schema_hash": "sha256:" + "3" * 64,
    "extract_model": "fixed",
    "stt_model": "fixed-stt",
    "embedding_model": "fixed-embed",
    "ingest_mode": "real",
    "extract_temperature": 0.0,
    "video_input_mode": "frames",
    "video_max_frames_to_model": 20,
    "frame_interval_sec": 3,
    "video_segment_sec": 0,
    "pipeline_version": "facts_then_cards/v1",
    "reuse_cards": False,
    "reuse_sources": False,
}
SOURCE_HASHES = {"scan-1": "sha256:" + "1" * 64}


def _campaign() -> dict:
    candidates = {
        "BASE": {"role": "CONTROL", "settings": SETTINGS},
        "BASE-AA": {"role": "CONTROL_REPEAT", "settings": SETTINGS},
        "W1": {"role": "CANDIDATE", "settings": SETTINGS},
    }
    schedule = []
    slot = 1
    for repeat in range(1, 4):
        for candidate in ("BASE", "W1", "BASE-AA"):
            schedule.append({
                "slot": slot,
                "store": "store-c",
                "candidate": candidate,
                "repeat": repeat,
                "label": f"sealed-{candidate}-{repeat}",
            })
            slot += 1
    return {
        "schema_version": "w-eval-campaign/v1",
        "campaign_id": "sealed-001",
        "status": "APPROVED",
        "approved_by": "reviewer",
        "approved_at": "2026-09-16T00:00:00Z",
        "split": "holdout",
        "stores": {
            "store-c": {
                "manifest_sha256": sha256_bytes(MANIFEST),
                "truth_sha256": "sha256:" + "2" * 64,
                "source_sha256": SOURCE_HASHES,
            }
        },
        "candidates": candidates,
        "schedule_method": "COUNTERBALANCED",
        "schedule_seed": "registered-seed",
        "schedule": schedule,
        "budgets": {
            "max_runs": 9,
            "max_source_bytes_per_run": 1000,
            "max_provider_attempts_per_run": 4,
            "max_provider_attempts_total": 36,
            "max_registration_cost_usd": 1.25,
        },
        "gates": {
            "min_repeats": 3,
            "min_positive_directions": 2,
            "min_net_improvement": 5,
            "must_have_regressions_allowed": 0,
            "monthly_operation_cost_krw": 3000,
        },
    }


def _validate(campaign: dict | None = None, *, candidate="BASE", repeat=1,
              label="sealed-BASE-1"):
    value = campaign or _campaign()
    raw = json.dumps(value, sort_keys=True).encode()
    return validate_campaign(
        value,
        campaign_bytes=raw,
        store="store-c",
        split="holdout",
        manifest_hash=sha256_bytes(MANIFEST),
        source_hashes=SOURCE_HASHES,
        source_bytes=500,
        runtime_settings=SETTINGS,
        candidate=candidate,
        repeat=repeat,
        label=label,
    )


def test_valid_campaign_selects_exact_scheduled_run():
    run = _validate()
    assert run.slot == 1
    assert run.max_provider_attempts == 4
    assert run.max_registration_cost_usd == 1.25


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c.update(status="DRAFT"), "승인된 캠페인"),
        (lambda c: c.update(split="dev"), "split"),
        (lambda c: c["stores"]["store-c"].update(manifest_sha256="sha256:" + "0" * 64),
         "manifest hash"),
        (lambda c: c["candidates"]["BASE"].update(settings={"model": "changed"}),
         "설정"),
        (lambda c: c.update(schedule_method="MANUAL"), "실행표 방식"),
        (lambda c: c["schedule"].pop(), "최소 3회"),
        (lambda c: c["budgets"].update(max_runs=1), "max_runs"),
        (lambda c: c["budgets"].update(max_source_bytes_per_run=499), "byte 예산"),
        (lambda c: c["gates"].update(must_have_regressions_allowed=1), "허용치는 0"),
    ],
)
def test_campaign_rejects_unregistered_or_underbudgeted_changes(change, message):
    campaign = deepcopy(_campaign())
    change(campaign)
    with pytest.raises(CampaignError, match=message):
        _validate(campaign)


def test_claim_is_immutable_and_same_slot_cannot_run_twice(tmp_path):
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(_campaign()), encoding="utf-8")
    run = _validate()

    claim = claim_campaign_run(path, run)
    assert claim.exists()
    append_campaign_event(path, run, "OPENED")

    with pytest.raises(CampaignError, match="이미 개봉 또는 시도"):
        claim_campaign_run(path, run)
    events = (path.with_suffix(".json.locks") / "events.jsonl").read_text("utf-8")
    assert '"state": "OPENED"' in events


def test_changed_campaign_cannot_reuse_existing_lock(tmp_path):
    path = tmp_path / "campaign.json"
    run = _validate()
    claim_campaign_run(path, run)
    changed = deepcopy(_campaign())
    changed["approved_by"] = "another-reviewer"
    changed_run = _validate(changed)

    with pytest.raises(CampaignError, match="다른 내용으로 잠긴"):
        claim_campaign_run(path, changed_run)


def test_schedule_cannot_skip_or_overlap_an_earlier_slot(tmp_path):
    path = tmp_path / "campaign.json"
    first = _validate()
    second = _validate(candidate="W1", repeat=1, label="sealed-W1-1")

    with pytest.raises(CampaignError, match="순서를 건너뛸 수 없다"):
        claim_campaign_run(path, second)
    claim_campaign_run(path, first)
    append_campaign_event(path, first, "SUCCEEDED", run_id=10,
                          ai_attempt_count=1, cost_usd="0.1")
    assert claim_campaign_run(path, second).exists()


def test_unknown_cost_in_prior_slot_blocks_the_next_slot(tmp_path):
    path = tmp_path / "campaign.json"
    first = _validate()
    second = _validate(candidate="W1", repeat=1, label="sealed-W1-1")
    claim_campaign_run(path, first)
    append_campaign_event(path, first, "FAILED", detail="provider ended before rollup")

    with pytest.raises(CampaignError, match="비용 관측이 없어"):
        claim_campaign_run(path, second)


def test_observed_budget_requires_complete_cost_and_stays_under_both_caps():
    run = _validate()
    enforce_observed_budget(run, {"ai_attempt_count": 4, "cost_usd": "1.25"})

    with pytest.raises(CampaignError, match="미관측 호출"):
        enforce_observed_budget(run, {"ai_attempt_count": 1, "cost_usd": None})
    with pytest.raises(CampaignError, match="attempt 예산 초과"):
        enforce_observed_budget(run, {"ai_attempt_count": 5, "cost_usd": "0.1"})
    with pytest.raises(CampaignError, match="등록비 예산 초과"):
        enforce_observed_budget(run, {"ai_attempt_count": 1, "cost_usd": "1.251"})


def test_total_budget_includes_prior_terminal_slots(tmp_path):
    path = tmp_path / "campaign.json"
    run = _validate()
    claim_campaign_run(path, run)
    append_campaign_event(path, run, "SUCCEEDED", run_id=1,
                          ai_attempt_count=35, cost_usd="1.20")
    later = _validate(candidate="W1", repeat=1, label="sealed-W1-1")

    with pytest.raises(CampaignError, match="전체 provider attempt"):
        enforce_observed_budget(later, {"ai_attempt_count": 2, "cost_usd": "0.01"}, path)
    with pytest.raises(CampaignError, match="등록비 예산 초과"):
        enforce_observed_budget(later, {"ai_attempt_count": 1, "cost_usd": "0.06"}, path)
