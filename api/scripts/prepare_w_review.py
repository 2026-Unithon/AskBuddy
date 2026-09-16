"""로컬 dev DB를 읽기 전용으로 보존·복구 감사·표본 추출한다. 유료 호출 없음."""
from __future__ import annotations
import argparse
import hashlib
import inspect
import json
import random
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

API = Path(__file__).resolve().parents[1]
ROOT = API.parent
sys.path.insert(0, str(API))
from app.team.extraction import SCORER_VERSION
from rescore_extract_report import rescore


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def rows(sql):
    """고정 로컬 컨테이너만 사용한다. .env의 운영 DSN은 읽지 않는다."""
    cmd = ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
           "supabase_db_AskBuddy", "psql", "-U", "postgres", "-d", "postgres",
           "-qAt", "-v", "ON_ERROR_STOP=1", "-c",
           f"select coalesce(json_agg(row_to_json(q)), '[]'::json) from ({sql}) q"]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def in_window(row, run):
    start, end = datetime.fromisoformat(run["started_at"]), datetime.fromisoformat(run["finished_at"])
    return all(start <= datetime.fromisoformat(row[k]) <= end for k in ("created_at", "updated_at") if row.get(k))


def validate_retained(run, report, cards, versions, ledger, truth, sources, manifest, compat_code=None):
    """원래 snapshot이 없다는 한계를 보존하고 남은 실행 데이터와의 정합만 검사한다."""
    old_truth = {r["fact_id"]: r for r in report["results"]}
    checks = dict(report_identity=report["run_id"] == run["run_id"] and report["store"] == run["store_slug"] and report["label"] == run["label"],
                  card_count=len(cards) == run["card_count"],
                  immutable_versions=len(versions) == len(cards) and all(v["version_no"] == 1 for v in versions),
                  creation_window=all(in_window(r, run) for r in [*cards, *versions, *ledger]),
                  truth_equal=len(old_truth) == len(truth) and all(
                      f["fact_id"] in old_truth and all(f.get(k) == old_truth[f["fact_id"]].get(k)
                          for k in ("subject", "variant", "attribute", "value", "must_have", "source_key")) for f in truth),
                  ledger_uncorrected=all(not f.get("corrected_at") and not f.get("is_superseded") for f in ledger))
    by_card = {v["card_id"]: v for v in versions}
    checks["version_content_equal"] = all(c["card_id"] in by_card and
        all(c[k] == by_card[c["card_id"]][k] for k in ("title", "content")) for c in cards)
    manifest_hashes = {s["sha256"] for s in manifest["sources"]}
    checks["source_hash_equal"] = {s["content_hash"] for s in sources} == manifest_hashes and all(
        report["settings"].get("source_hashes", {}).get(s["source_key"]) == s["sha256"][:16] for s in manifest["sources"])
    checks["original_files_equal"] = all(hashlib.sha256((API/"eval/data"/run["store_slug"].replace("eval-", "store-")/s["file"]).read_bytes()).hexdigest() == s["sha256"] for s in manifest["sources"])
    # dirty checkout의 잃어버린 변경은 복원하지 못하므로 커밋판 재생을 별도로 기록한다.
    base = run["code_version"].split("-dirty")[0].split("-")[0]
    attempts = []
    for code in dict.fromkeys([base, *([compat_code] if compat_code else [])]):
      try:
        source = subprocess.run(["git", "show", f"{code}:api/app/team/extraction.py"], cwd=ROOT,
                                check=True, capture_output=True, text=True).stdout
        module = types.ModuleType("w_legacy_review")
        sys.modules[module.__name__] = module
        exec(compile(source, "<repository legacy scorer>", "exec"), module.__dict__)
        supports_axis = "require_variant" in inspect.signature(module.match_fact).parameters
        axis = module.variant_axis(truth) if supports_axis else {}
        mismatch = []
        for fact in truth:
            kwargs = {"require_variant": axis.get(module.normalize(fact["subject"]), False)} if supports_axis else {}
            matched = module.match_fact(fact, cards, **kwargs)
            old = old_truth[fact["fact_id"]]
            if matched.verdict != old["verdict"] or matched.card_id != old["card_id"]:
                mismatch.append(fact["fact_id"])
        attempts.append(dict(mismatch_ids=mismatch, code=code, scorer_hash="sha256:"+hashlib.sha256(source.encode()).hexdigest(),
                             mode="RECORDED_BASE_COMMIT" if code == base else "EXPLICIT_COMPATIBILITY_COMMIT_NOT_ORIGINAL_DIRTY_CODE"))
        if not mismatch:
            break
      except (subprocess.CalledProcessError, KeyError) as exc:
        attempts.append(dict(code=code,error_type=type(exc).__name__))
    checks["committed_scorer_replay_equal"] = any(a.get("mismatch_ids") == [] for a in attempts)
    replay = dict(attempts=attempts,dirty_checkout_unrecoverable="dirty" in run["code_version"])
    return checks, replay


def write_new(path, data):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, default=str)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compat-code", help="원래 dirty 코드가 아닌 호환 커밋; 재생 근거로만 명시적으로 기록")
    args = ap.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(API/"eval/reports") or out.exists():
        ap.error("새 Git 제외 eval/reports 하위 디렉터리만 허용한다")
    out.mkdir(parents=True)
    stores = rows("select store_id,store_slug from stores where store_slug in ('eval-a','eval-b') order by store_slug")
    audit, candidates, inventory = [], [], []
    for store in stores:
        store_id, slug = int(store["store_id"]), store["store_slug"]
        store_dir = API/"eval/data"/slug.replace("eval-", "store-")
        manifest = json.loads((store_dir/"manifest.json").read_text())
        truth = json.loads((store_dir/"truth/facts.json").read_text())["facts"]
        cards = rows(f"select card_id,title,content,source_id,created_at,updated_at from knowledge_cards where store_id={store_id} order by card_id")
        versions = rows(f"select version_id,card_id,version_no,title,content,created_at from card_versions where store_id={store_id} order by card_id,version_no")
        ledger = rows(f"select * from source_facts where store_id={store_id} order by fact_id")
        sources = rows(f"select source_id,source_type,content_hash,created_at,processed_at from sources where store_id={store_id} order by source_id")
        runs = rows(f"select run_id,label,status,card_count,code_version,started_at,finished_at from extraction_runs where store_id={store_id} and label ~ '^(BASE|BASE-AA|W1|W1-AA)#[123]$' order by run_id")
        source_types = {s["source_key"]:s["type"] for s in manifest["sources"]}
        source_key = {s["sha256"]:s["source_key"] for s in manifest["sources"]}
        originals = []
        for source in sources:
            sid = int(source["source_id"])
            if source["source_type"] in {"VOICE", "VIDEO"}:
                table = "source_voice" if source["source_type"] == "VOICE" else "source_video"
                record = rows(f"select x.transcript from {table} x join sources s on s.source_id=x.source_id where s.store_id={store_id} and s.source_id={sid}")
                originals.append(dict(source_key=source_key[source["content_hash"]],type=source["source_type"],transcript=record[0]["transcript"] if record else None))
        current = dict(run_id=max(r["run_id"] for r in runs),store=slug,label="CURRENT_RETAINED_STATE",
                       inputs=dict(cards=cards,ledger=ledger,truth=truth,source_types=source_types),manifest=manifest,
                       originals=originals,versions=versions,sources=sources,scope="REVIEW_NOT_HISTORICAL_SNAPSHOT")
        current_score = rescore(current)
        write_new(out/f"current_{slug}.json",current)
        write_new(out/f"current_{slug}_scored.json",current_score)
        by_truth={f["fact_id"]:f for f in truth}
        by_card={c["card_id"]:c for c in cards}
        for row in current_score["results"]:
            candidates.append(dict(store=slug,truth=by_truth[row["fact_id"]],scorer=row,
                                   card=by_card.get(row["card_id"]),reviewer_kind="AI",human_verdict=None))
        inventory.append(dict(store=slug,card_count=len(cards),ledger_count=len(ledger),
                              covered=current_score["metrics"]["covered"],undetermined=current_score["metrics"]["undetermined"]))
        for run in runs:
            run["store_slug"] = slug
            report_path = list((API/"eval/reports").glob(f"extract{run['run_id']:05d}_{slug}_*.json"))
            item=dict(run_id=run["run_id"],store=slug,label=run["label"],status="NOT_RECOVERED",reason="cards/versions/ledger removed by resets")
            if not run["card_count"]:
                item.update(status="INVALID_EMPTY_RUN",reason="zero-card run; not a baseline")
            elif report_path and all(in_window(c,run) for c in cards) and len(cards)==run["card_count"]:
                original_report=json.loads(report_path[0].read_text())
                checks,replay=validate_retained(run,original_report,cards,versions,ledger,truth,sources,manifest,args.compat_code)
                item.update(checks=checks,legacy_replay=replay)
                if all(checks.values()):
                    recovered={**original_report,"inputs":current["inputs"],"recovery":dict(checks=checks,legacy_replay=replay,original_report_hash=digest(original_report),
                               evidence="RETAINED_DB_STATE_WITH_TIMESTAMP_CONTENT_TRUTH_HASH_AND_REPLAY_CHECKS",
                               limitation="not an originally frozen input snapshot; dirty code state unavailable")}
                    write_new(out/report_path[0].name,recovered)
                    scored=rescore(recovered)
                    scored["recovery"]=recovered["recovery"]
                    write_new(out/f"rescore_{run['run_id']}_{slug}.json",scored)
                    item.update(status="RETAINED_STATE_RECOVERED",reason="validated retained data; retrospective rescore only",new_metrics={k:scored["metrics"][k] for k in ("covered","undetermined","partial","missing")})
                else:
                    item.update(reason="retained state candidate failed one or more provenance checks")
            audit.append(item)
    rng=random.Random(20260915)
    covered=sorted((c for c in candidates if c["scorer"]["verdict"]=="COVERED"),key=lambda c:(c["store"],c["truth"]["fact_id"]))
    sample=rng.sample(covered,min(15,len(covered)))
    held=[c for c in candidates if c["scorer"]["verdict"]=="UNDETERMINED"]
    write_new(out/"review_packet.json",dict(seed=20260915,scorer_version=SCORER_VERSION,
        inputs_hash=digest(candidates),covered_population=len(covered),covered_sample=sample,all_undetermined=held,
        scope="AI_REVIEW_AND_HUMAN_CONFIRMATION_PACKET_NOT_HUMAN_ACCEPTANCE"))
    write_new(out/"recovery_audit.json",dict(inventory=inventory,runs=audit,scope="DEV_ONLY_LOCAL_READ_ONLY_NO_REEXTRACTION"))
    print(json.dumps(dict(inventory=inventory,recovery_statuses={s:sum(r["status"]==s for r in audit) for s in sorted({r["status"] for r in audit})},
                     covered_sample=len(sample),undetermined=len(held),out=str(out)),ensure_ascii=False))


if __name__=="__main__":
    main()
