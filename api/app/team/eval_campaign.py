"""W 평가 캠페인의 사전등록·동결 검증.

holdout 정답을 읽기 전에 실행 권한, 입력 지문, 후보 설정, 실행표와 예산을
검사한다. 검증을 통과한 첫 시도는 파일 잠금으로 남아 같은 slot의 재사용을 막는다.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "w-eval-campaign/v1"
ROLES = {"CONTROL", "CANDIDATE", "CONTROL_REPEAT"}
SCHEDULE_METHODS = {"RANDOMIZED", "COUNTERBALANCED"}
LOCKED_SETTING_KEYS = {
    "scorer_version", "code_version", "extract_prompt_version",
    "assemble_prompt_version", "extraction_schema_hash", "extract_model",
    "stt_model", "embedding_model", "ingest_mode", "extract_temperature",
    "video_input_mode", "video_max_frames_to_model", "frame_interval_sec",
    "video_segment_sec", "pipeline_version", "reuse_cards", "reuse_sources",
}


class CampaignError(ValueError):
    """캠페인이 사전등록 계약을 충족하지 못했다."""


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignError(message)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:")


@dataclass(frozen=True)
class CampaignRun:
    campaign_id: str
    campaign_hash: str
    slot: int
    store: str
    candidate: str
    repeat: int
    label: str
    truth_hash: str
    source_hashes: dict[str, str]
    max_source_bytes: int
    max_provider_attempts: int
    max_provider_attempts_total: int
    max_registration_cost_usd: float


def validate_campaign(
    campaign: dict[str, Any], *, campaign_bytes: bytes, store: str,
    split: str, manifest_hash: str, source_hashes: dict[str, str],
    source_bytes: int | None, runtime_settings: dict[str, Any], candidate: str,
    repeat: int, label: str,
) -> CampaignRun:
    """현재 실행이 사전등록된 한 slot과 정확히 같은지 확인한다."""
    _require(campaign.get("schema_version") == SCHEMA_VERSION,
             f"schema_version은 {SCHEMA_VERSION} 이어야 한다")
    campaign_id = campaign.get("campaign_id")
    _require(isinstance(campaign_id, str) and bool(campaign_id.strip()),
             "campaign_id가 필요하다")
    _require(campaign.get("status") == "APPROVED", "승인된 캠페인만 실행할 수 있다")
    _require(bool(campaign.get("approved_by")) and bool(campaign.get("approved_at")),
             "approved_by와 approved_at이 필요하다")
    _require(campaign.get("split") == split, "캠페인 split과 자료 split이 다르다")

    stores = campaign.get("stores")
    _require(isinstance(stores, dict) and store in stores,
             f"캠페인에 매장 {store}가 등록되지 않았다")
    binding = stores[store]
    _require(isinstance(binding, dict), f"매장 {store} binding 형식이 잘못됐다")
    _require(binding.get("manifest_sha256") == manifest_hash,
             "manifest hash가 사전등록 값과 다르다")
    expected_truth_hash = binding.get("truth_sha256")
    _require(_sha256(expected_truth_hash), "truth_sha256은 전체 SHA-256이어야 한다")
    expected_sources = binding.get("source_sha256")
    _require(isinstance(expected_sources, dict) and bool(expected_sources)
             and all(_sha256(value) for value in expected_sources.values()),
             "source_sha256에는 원본별 전체 SHA-256이 필요하다")
    _require(expected_sources == source_hashes,
             "원본 목록 또는 source hash가 사전등록 값과 다르다")
    for store_name, store_binding in stores.items():
        _require(isinstance(store_name, str) and isinstance(store_binding, dict),
                 "stores binding 형식이 잘못됐다")
        registered_sources = store_binding.get("source_sha256")
        _require(isinstance(registered_sources, dict) and bool(registered_sources)
                 and all(_sha256(value) for value in registered_sources.values()),
                 f"매장 {store_name}의 source_sha256이 잘못됐다")

    candidates = campaign.get("candidates")
    _require(isinstance(candidates, dict) and candidate in candidates,
             f"후보 {candidate}가 등록되지 않았다")
    selected = candidates[candidate]
    _require(isinstance(selected, dict) and selected.get("role") in ROLES,
             "후보 role은 CONTROL/CANDIDATE/CONTROL_REPEAT 중 하나여야 한다")
    _require(set(runtime_settings) == LOCKED_SETTING_KEYS,
             "runtime 설정 동결 필드가 빠졌거나 추가됐다")
    code = runtime_settings.get("code_version")
    _require(isinstance(code, str) and code != "unknown" and not code.endswith("-dirty"),
             "캠페인은 commit된 clean 코드에서만 실행할 수 있다")
    _require(runtime_settings.get("extraction_schema_hash", "").startswith("sha256:"),
             "추출 schema hash가 필요하다")
    _require(selected.get("settings") == runtime_settings,
             "현재 모델·프롬프트·schema·전처리 설정이 등록 후보와 다르다")
    roles = {item.get("role") for item in candidates.values() if isinstance(item, dict)}
    _require(ROLES <= roles, "CONTROL/CANDIDATE/CONTROL_REPEAT 후보를 모두 등록해야 한다")

    method = campaign.get("schedule_method")
    _require(method in SCHEDULE_METHODS, "실행표 방식은 RANDOMIZED 또는 COUNTERBALANCED여야 한다")
    _require(bool(campaign.get("schedule_seed")), "고정된 schedule_seed가 필요하다")
    schedule = campaign.get("schedule")
    _require(isinstance(schedule, list) and bool(schedule), "비어 있지 않은 실행표가 필요하다")
    _require(all(isinstance(item, dict) for item in schedule), "실행표 항목은 객체여야 한다")
    _require(all(item.get("store") in stores for item in schedule),
             "실행표에 등록되지 않은 매장이 있다")
    _require(all(_positive_int(item.get("repeat"))
                 and isinstance(item.get("label"), str) and bool(item.get("label"))
                 for item in schedule),
             "각 실행표 항목에는 양의 repeat와 label이 필요하다")
    sequences = [item.get("slot") for item in schedule]
    _require(sequences == list(range(1, len(schedule) + 1)),
             "실행표 slot은 1부터 빠짐없이 사전 순서대로 있어야 한다")
    run_keys = [(item.get("store"), item.get("candidate"), item.get("repeat")) for item in schedule]
    _require(len(run_keys) == len(set(run_keys)), "실행표에 중복된 store/candidate/repeat가 있다")
    labels = [item.get("label") for item in schedule]
    _require(len(labels) == len(set(labels)), "실행표 label은 서로 달라야 한다")
    _require(all(item.get("candidate") in candidates for item in schedule),
             "실행표에 등록되지 않은 후보가 있다")
    for candidate_name in candidates:
        candidate_runs = [item for item in schedule if item.get("candidate") == candidate_name]
        _require(len(candidate_runs) >= 3, f"후보 {candidate_name}의 반복은 최소 3회여야 한다")
    matches = [item for item in schedule if (
        item.get("store") == store and item.get("candidate") == candidate
        and item.get("repeat") == repeat and item.get("label") == label
    )]
    _require(len(matches) == 1, "현재 store/candidate/repeat/label에 해당하는 실행표 slot이 없다")

    budgets = campaign.get("budgets")
    _require(isinstance(budgets, dict), "budgets가 필요하다")
    max_runs = budgets.get("max_runs")
    max_bytes = budgets.get("max_source_bytes_per_run")
    max_attempts = budgets.get("max_provider_attempts_per_run")
    total_attempts = budgets.get("max_provider_attempts_total")
    max_cost = budgets.get("max_registration_cost_usd")
    _require(_positive_int(max_runs) and max_runs >= len(schedule), "max_runs가 실행표보다 작다")
    _require(_positive_int(max_bytes), "max_source_bytes_per_run은 양의 정수여야 한다")
    if source_bytes is not None:
        _require(source_bytes <= max_bytes, "입력 원본 크기가 실행당 byte 예산을 넘는다")
    _require(_positive_int(max_attempts) and max_attempts >= len(source_hashes),
             "실행당 provider attempt 예산이 source 수보다 작다")
    minimum_total_attempts = sum(
        len(stores[item["store"]]["source_sha256"]) for item in schedule
    )
    _require(_positive_int(total_attempts) and total_attempts >= minimum_total_attempts,
             "전체 provider attempt 예산이 실행표의 source 최소 호출 수보다 작다")
    _require(isinstance(max_cost, (int, float)) and not isinstance(max_cost, bool)
             and math.isfinite(float(max_cost)) and max_cost >= 0,
             "max_registration_cost_usd는 0 이상의 수여야 한다")

    gates = campaign.get("gates")
    _require(isinstance(gates, dict), "결과 확인 전에 고정한 gates가 필요하다")
    _require(gates.get("min_repeats") == 3, "min_repeats는 3이어야 한다")
    _require(gates.get("min_positive_directions") == 2,
             "min_positive_directions는 2여야 한다")
    _require(gates.get("min_net_improvement") == 5,
             "min_net_improvement는 5여야 한다")
    _require(gates.get("must_have_regressions_allowed") == 0,
             "must_have 악화 허용치는 0이어야 한다")
    _require(gates.get("monthly_operation_cost_krw") == 3000,
             "월 운영 변동비 상한은 3000원이어야 한다")

    return CampaignRun(
        campaign_id=campaign_id,
        campaign_hash=sha256_bytes(campaign_bytes),
        slot=int(matches[0]["slot"]),
        store=store,
        candidate=candidate,
        repeat=repeat,
        label=label,
        truth_hash=expected_truth_hash,
        source_hashes=expected_sources,
        max_source_bytes=max_bytes,
        max_provider_attempts=max_attempts,
        max_provider_attempts_total=total_attempts,
        max_registration_cost_usd=float(max_cost),
    )


def claim_campaign_run(campaign_path: Path, run: CampaignRun) -> Path:
    """캠페인/slot을 원자적으로 잠근다. 같은 slot 재실행은 거절한다."""
    lock_dir = campaign_path.with_suffix(campaign_path.suffix + ".locks")
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    master_path = lock_dir / "campaign.json"
    master = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": run.campaign_id,
        "campaign_hash": run.campaign_hash,
    }
    try:
        fd = os.open(master_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = json.loads(master_path.read_text("utf-8"))
        _require(existing == master, "이미 다른 내용으로 잠긴 캠페인이다")
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(master, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")

    # 실행표 순서를 건너뛰거나 두 slot을 동시에 돌리지 않는다.
    event_path = lock_dir / "events.jsonl"
    terminal_slots: set[int] = set()
    terminal_events: dict[int, dict[str, Any]] = {}
    if event_path.exists():
        try:
            for line in event_path.read_text("utf-8").splitlines():
                event = json.loads(line)
                if event.get("state") in {"SUCCEEDED", "FAILED"}:
                    slot = int(event["slot"])
                    terminal_slots.add(slot)
                    terminal_events[slot] = event
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CampaignError("캠페인 event 기록이 손상됐다") from exc
    required_slots = set(range(1, run.slot))
    _require(required_slots <= terminal_slots,
             "앞선 실행표 slot이 아직 종료되지 않아 순서를 건너뛸 수 없다")
    prior_attempts = 0
    prior_cost = Decimal("0")
    for slot in required_slots:
        event = terminal_events[slot]
        _require(event.get("ai_attempt_count") is not None and event.get("cost_usd") is not None,
                 "앞선 slot의 비용 관측이 없어 다음 실행을 시작할 수 없다")
        try:
            prior_attempts += int(event["ai_attempt_count"])
            prior_cost += Decimal(str(event["cost_usd"]))
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise CampaignError("앞선 slot의 비용 event 기록이 손상됐다") from exc
    _require(prior_attempts < run.max_provider_attempts_total,
             "캠페인 전체 provider attempt 예산이 이미 소진됐다")
    _require(prior_cost < Decimal(str(run.max_registration_cost_usd)),
             "캠페인 등록비 예산이 이미 소진됐다")

    claim_path = lock_dir / f"slot-{run.slot:04d}.json"
    claim = {
        **master,
        "slot": run.slot,
        "store": run.store,
        "candidate": run.candidate,
        "repeat": run.repeat,
        "label": run.label,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
        "state": "CLAIMED",
    }
    try:
        fd = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CampaignError(f"실행표 slot {run.slot}은 이미 개봉 또는 시도됐다") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(claim, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    return claim_path


def enforce_observed_budget(
    run: CampaignRun, cost: dict[str, Any] | None, campaign_path: Path | None = None,
) -> dict[str, Any]:
    """호출 후 실제 원장에서 실행당·캠페인 전체 예산을 강제한다."""
    _require(cost is not None, "캠페인 원가/호출 예산을 확인할 수 없다")
    attempts = cost.get("ai_attempt_count")
    _require(isinstance(attempts, int) and attempts <= run.max_provider_attempts,
             f"provider attempt 예산 초과: {attempts} > {run.max_provider_attempts}")
    observed = cost.get("cost_usd")
    _require(observed is not None, "미관측 호출이 있어 캠페인 등록비 예산을 확인할 수 없다")
    try:
        observed_cost = Decimal(str(observed))
    except (InvalidOperation, ValueError) as exc:
        raise CampaignError("관측 등록비 형식이 잘못됐다") from exc
    _require(observed_cost.is_finite(), "관측 등록비 형식이 잘못됐다")
    prior_attempts = 0
    prior_cost = Decimal("0")
    if campaign_path is not None:
        event_path = campaign_path.with_suffix(campaign_path.suffix + ".locks") / "events.jsonl"
        if event_path.exists():
            terminal_by_slot: dict[int, dict[str, Any]] = {}
            try:
                for line in event_path.read_text("utf-8").splitlines():
                    event = json.loads(line)
                    if event.get("state") in {"SUCCEEDED", "FAILED"}:
                        terminal_by_slot[int(event["slot"])] = event
                for slot, event in terminal_by_slot.items():
                    if slot == run.slot:
                        continue
                    _require(event.get("ai_attempt_count") is not None
                             and event.get("cost_usd") is not None,
                             "앞선 slot의 비용 관측이 없어 캠페인 전체 예산을 확인할 수 없다")
                    prior_attempts += int(event["ai_attempt_count"])
                    prior_cost += Decimal(str(event["cost_usd"]))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise CampaignError("캠페인 비용 event 기록이 손상됐다") from exc
    _require(prior_attempts + attempts <= run.max_provider_attempts_total,
             "캠페인 전체 provider attempt 예산을 초과했다")
    total_cost = prior_cost + observed_cost
    _require(total_cost <= Decimal(str(run.max_registration_cost_usd)),
             f"등록비 예산 초과: {total_cost} > {run.max_registration_cost_usd} USD")
    return {"ai_attempt_count": attempts, "cost_usd": str(observed_cost)}


def append_campaign_event(campaign_path: Path, run: CampaignRun, state: str,
                          *, run_id: int | None = None, detail: str | None = None,
                          ai_attempt_count: int | None = None,
                          cost_usd: str | None = None) -> None:
    """불변 claim 옆에 시작·성공·실패 이력을 추가한다."""
    _require(state in {"OPENED", "STARTED", "SUCCEEDED", "FAILED"}, "알 수 없는 캠페인 상태다")
    event = {
        "campaign_id": run.campaign_id,
        "campaign_hash": run.campaign_hash,
        "slot": run.slot,
        "state": state,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "detail": detail,
        "ai_attempt_count": ai_attempt_count,
        "cost_usd": cost_usd,
    }
    event_path = campaign_path.with_suffix(campaign_path.suffix + ".locks") / "events.jsonl"
    fd = os.open(event_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
