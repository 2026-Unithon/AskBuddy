"""Phase 0 외부 모델 관찰을 자동으로 돌린다 (Claude Code · Codex CLI, 구독 사용).

`추출결과/관찰/<로직>/<형식>/자료N/원본/` 에 파일이 있고 실행 폴더의 `result.json` 이 비어 있는 칸을 찾아,
실행마다 **저장소 밖 새 임시 폴더**에 원본만 복사해 같은 지시문으로 돌린다. 결과·실행 기록·격리 검사를 칸 폴더에 넣는다.
사용법·규칙은 `추출결과/관찰/README.md`. 설계: docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md Phase 0.

    api/.venv/bin/python api/scripts/run_observation.py --list            # 할 일 목록만
    api/.venv/bin/python api/scripts/run_observation.py --dry-run         # 명령만 보여 주기
    api/.venv/bin/python api/scripts/run_observation.py --max 2           # 2개 실행만
    api/.venv/bin/python api/scripts/run_observation.py --stt             # 음성·영상 전사 먼저(유료, whisper-1)
    api/.venv/bin/python api/scripts/run_observation.py --only PROCEDURE --runs claude-sonnet-5.5
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
OBS_DIR = ROOT / "추출결과" / "관찰"
WORK_ROOT = pathlib.Path("/tmp/askbuddy-observe")
STT_DIR_NAME = "원본_전사"
OWNER_PLACEHOLDER = "(여기에 직원 질문을 붙여넣으세요)"
MEDIA_EXT = {".mp3", ".m4a", ".wav", ".mp4", ".mov", ".avi"}

# 실행 이름 → (도구, 모델 id, 추론 수준). 모든 칸에 같은 네 실행을 돌린다.
RUN_MATRIX = {
    "claude-opus-5.5": ("claude", "claude-opus-5-5", "high"),
    "claude-sonnet-5.5": ("claude", "claude-sonnet-5-5", "high"),
    "gpt-sol-6.1": ("codex", "gpt-6.1-sol", "high"),
    "gpt-luna-6.0": ("codex", "gpt-6-luna", "high"),
}

# 모든 실행에 똑같이 붙는 출력 안내. 지시문 본문은 칸의 지시문.md 그대로.
OUTPUT_SUFFIX = """

━━ 실행 환경 안내 (모든 실행 공통) ━━
- 위에서 "첨부했습니다" 라고 한 자료는 이 작업 폴더의 ./input/ 에 있습니다. {stt_note}
- 다 끝나면 두 파일을 저장하세요.
  ./out/result.json — 2부 JSON 하나만(설명 문장 없이).
  ./out/worklog.md — 1부 작업 기록(실행한 코드 원문 포함)과 3부 자기 점검. "## 3부" 제목으로 3부를 시작하세요.
- 파일이 길면 한 번에 쓰지 말고 여러 번에 나눠 이어 쓰고, 다 쓴 뒤 두 파일이 끝까지 저장됐는지 확인하세요.
- ./input 과 ./out 밖의 파일·폴더는 읽거나 쓰지 마세요. 인터넷을 쓰지 마세요. 자료에 없는 지식으로 채우지 마세요.
- 필요한 도구(파이썬 라이브러리, ffmpeg 등)는 이 컴퓨터에 있는 것을 자유롭게 쓰세요.
"""
_STT_NOTE = "음성·영상의 말을 글로 옮긴 전사본(시간 표시 포함)이 ./input/_전사/ 에 있습니다. 쓰든 안 쓰든 자유입니다."

# API 환산 단가(USD / 100만 토큰). 구독으로 돌지만 비교용으로 환산한다. 모르는 모델은 None(토큰만 기록)
API_RATES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}
BASELINE_FILE = "_baseline.json"
BASELINE_PROMPT = "OK 만 출력하세요."

CLAUDE_DISALLOWED = ["WebSearch", "WebFetch", "Task", "Agent", "Artifact", "ArtifactComments",
                     "ArtifactData", "DesignSync", "CronCreate", "CronDelete", "CronList",
                     "EnterWorktree", "ExitWorktree", "RemoteTrigger", "SendMessage"]


def files_in(d: pathlib.Path) -> list[pathlib.Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file() and not p.name.startswith("."))


def pending(root: pathlib.Path = OBS_DIR, only: str | None = None,
            runs: list[str] | None = None) -> list[tuple[pathlib.Path, str]]:
    """(자료 폴더, 실행 이름) 중 원본이 있고 결과가 비어 있는 것. 점주답변은 질문을 채웠을 때만."""
    out = []
    for case in sorted(root.glob("*/*/자료*")):
        if only and only.upper() not in str(case.relative_to(root)).upper():
            continue
        if not files_in(case / "원본"):
            continue
        prompt = case / "지시문.md"
        if not prompt.exists() or OWNER_PLACEHOLDER in prompt.read_text():
            continue
        for run in (runs or list(RUN_MATRIX)):
            result = case / run / "result.json"
            if not result.exists() or result.stat().st_size == 0:
                out.append((case, run))
    return out


def build_prompt(case: pathlib.Path) -> str:
    has_stt = bool(files_in(case / STT_DIR_NAME))
    return (case / "지시문.md").read_text().rstrip() + OUTPUT_SUFFIX.format(stt_note=_STT_NOTE if has_stt else "")


def codex_bin() -> str:
    if os.environ.get("CODEX_BIN"):
        return os.environ["CODEX_BIN"]
    found = shutil.which("codex")
    if found:
        return found
    cands = sorted(pathlib.Path.home().glob(".vscode/extensions/openai.chatgpt-*/bin/*/codex"))
    if not cands:
        raise RuntimeError("codex 실행 파일을 찾지 못했다. CODEX_BIN 환경 변수로 경로를 준다")
    return str(cands[-1])


def command(run: str, work: pathlib.Path) -> tuple[list[str], dict[str, str]]:
    tool, model, effort = RUN_MATRIX[run]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "ANTHROPIC_", "GEMINI_"))}
    if tool == "claude":
        cmd = ["claude", "-p", "--model", model, "--effort", effort,
               "--setting-sources", "local", "--strict-mcp-config", "--no-session-persistence",
               "--permission-mode", "bypassPermissions", "--output-format", "stream-json", "--verbose",
               "--disallowedTools", *CLAUDE_DISALLOWED]
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "64000"  # 긴 파일 쓰기가 잘리지 않게
        return cmd, env
    home = work / ".codex_home"
    env["CODEX_HOME"] = str(home)
    cmd = [codex_bin(), "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
           "-C", str(work), "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
           "--ignore-rules", "--sandbox", "workspace-write", "--json", "-"]
    return cmd, env


def prepare(case: pathlib.Path, run: str) -> pathlib.Path:
    """저장소 밖 새 폴더에 원본(과 전사본)만 복사한다."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = WORK_ROOT / f"{stamp}-{run}"
    (work / "input").mkdir(parents=True)
    (work / "out").mkdir()
    for f in files_in(case / "원본"):
        dest = work / "input" / f.relative_to(case / "원본")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    for f in files_in(case / STT_DIR_NAME):
        dest = work / "input" / "_전사" / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    if RUN_MATRIX[run][0] == "codex":
        (work / ".codex_home").mkdir()
        shutil.copy2(pathlib.Path.home() / ".codex" / "auth.json", work / ".codex_home" / "auth.json")
    return work


_PATH_RE = re.compile(r"(?:/Users/|/private/var/|/home/|~/)[^\s\"'`]*")
_NET_RE = re.compile(r"\b(?:curl|wget|https?://)")


def audit(transcript: str, work: pathlib.Path) -> dict:
    """작업 폴더 밖 경로·인터넷 사용 흔적. 모델이 쓴 명령·도구 입력에서 찾는다(보수적으로 의심만 표시)."""
    allowed = (str(work), str(work.resolve()), "/tmp/askbuddy-observe", "/private/tmp/askbuddy-observe")
    outside, net = set(), set()
    for line in transcript.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        blob = json.dumps(_tool_inputs(ev), ensure_ascii=False)
        for m in _PATH_RE.findall(blob):
            if not m.startswith(allowed) and "/.venv/" not in m and "/site-packages/" not in m:
                outside.add(m[:200])
        net.update(_NET_RE.findall(blob))
    return {"outside_paths": sorted(outside), "network": sorted(net), "suspect": bool(outside or net)}


def _tool_inputs(ev: dict) -> list:
    """Claude stream-json 의 tool_use 입력, Codex JSONL 의 명령 실행 항목만 뽑는다."""
    found = []
    msg = ev.get("message") if isinstance(ev.get("message"), dict) else None
    if msg and ev.get("type") == "assistant":
        found += [b.get("input") for b in msg.get("content", []) if isinstance(b, dict) and b.get("type") == "tool_use"]
    item = ev.get("item") if isinstance(ev.get("item"), dict) else None
    if item and item.get("type") in ("command_execution", "local_shell_call", "file_change", "mcp_tool_call", "web_search"):
        found.append({k: item.get(k) for k in ("command", "changes", "query", "arguments") if k in item})
    return found


def _events(lines: list[tuple[float, str]]):
    for t, line in lines:
        try:
            yield t, json.loads(line)
        except ValueError:
            continue


def calls_of(lines: list[tuple[float, str]], tool: str) -> list[dict]:
    """모델 호출별 입력·출력 토큰. Claude 는 메시지 id 별 usage(중복 제거), Codex 는 턴 합계를 호출 수로 나눈 추정."""
    if tool == "claude":
        seen, calls = set(), []
        for _, ev in _events(lines):
            msg = ev.get("message") if ev.get("type") == "assistant" and isinstance(ev.get("message"), dict) else None
            if not msg or msg.get("id") in seen:
                continue
            seen.add(msg.get("id"))
            u = msg.get("usage") or {}
            calls.append({"input": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                          + u.get("cache_read_input_tokens", 0), "output": u.get("output_tokens", 0)})
        return calls
    total_in = total_out = 0
    actions = 0
    for _, ev in _events(lines):
        if ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            total_in += u.get("input_tokens", 0)
            total_out += u.get("output_tokens", 0) + u.get("reasoning_output_tokens", 0)
        item = ev.get("item") if isinstance(ev.get("item"), dict) else None
        if ev.get("type") == "item.completed" and item and item.get("type") in (
                "command_execution", "file_change", "mcp_tool_call", "local_shell_call"):
            actions += 1
    n = actions + 1  # 도구 호출마다 한 번 + 마지막 답 한 번(추정)
    return [{"input": total_in / n, "output": total_out / n, "estimated": True} for _ in range(n)]


def measure(lines: list[tuple[float, str]], run: str, baseline: dict | None) -> dict:
    """순수 측정: 기본 지시(하네스 시스템 프롬프트·도구 정의)와 CLI 기동 시간을 뺀다.

    - 순수 입력 = 호출마다 (입력 토큰 − 기본 지시 토큰) 의 합. 기본 지시 토큰은 같은 도구·모델에 "OK 만 출력" 을 보낸 첫 호출 입력(_baseline.json).
    - 출력 = 모델이 낸 토큰 전부(생각 포함).
    - 순수 시간 = 기동이 끝난 시점(Claude system init / Codex thread.started) → 마지막 이벤트.
    - API 환산 = 순수 입력 × 입력 단가 + 출력 × 출력 단가(캐시 할인 무시 = 상한). 단가 모르는 모델은 None.
    """
    tool, model, _ = RUN_MATRIX[run]
    calls = calls_of(lines, tool)
    base = (baseline or {}).get("call_input")
    raw_in = sum(c["input"] for c in calls)
    out = sum(c["output"] for c in calls)
    pure_in = sum(max(0.0, c["input"] - base) for c in calls) if base is not None else None
    start = last = None
    turns = cost_equiv = None
    result_ok = None  # Claude 최종 결과 이벤트의 성공 여부(Codex 는 None)
    for t, ev in _events(lines):
        if start is None and ((ev.get("type") == "system" and ev.get("subtype") == "init")
                              or ev.get("type") == "thread.started"):
            start = t
        last = t
        if ev.get("type") == "result":
            turns, cost_equiv = ev.get("num_turns"), ev.get("total_cost_usd")
            result_ok = ev.get("subtype") == "success" and not ev.get("is_error")
    if tool == "claude":
        # 출력 토큰은 메시지 시작 시점 usage 에 없다 → 최종 result 의 합계를 쓴다
        for _, ev in _events(lines):
            if ev.get("type") == "result" and isinstance(ev.get("usage"), dict):
                out = ev["usage"].get("output_tokens", out)
    rate = API_RATES.get(model)
    pure_cost = (round((pure_in * rate[0] + out * rate[1]) / 1e6, 4)
                 if rate and pure_in is not None else None)
    return {
        "calls": len(calls), "calls_estimated": tool == "codex", "turns": turns,
        "raw_input_tokens": round(raw_in), "output_tokens": round(out),
        "baseline_call_input_tokens": base, "pure_input_tokens": None if pure_in is None else round(pure_in),
        "pure_sec": None if start is None or last is None else round(last - start, 1),
        "pure_cost_usd_upper": pure_cost, "harness_cost_usd_equiv": cost_equiv, "result_ok": result_ok,
    }


def count_results(path: pathlib.Path) -> int | None:
    try:
        return len(json.loads(path.read_text()).get("results", []))
    except (ValueError, OSError, AttributeError):
        return None


def update_run_sheet(case: pathlib.Path, run: str, cells: list[str]) -> None:
    sheet = case / "RUN_SHEET.md"
    lines = sheet.read_text().splitlines() if sheet.exists() else []
    row = "| " + " | ".join([run, *cells]) + " |"
    for i, line in enumerate(lines):
        if line.startswith(f"| {run} |"):
            lines[i] = row
            break
    else:
        lines.append(row)
    sheet.write_text("\n".join(lines) + "\n")


def _stream(cmd: list[str], prompt: str, cwd: pathlib.Path, env: dict, timeout_s: int):
    """명령을 돌리며 stdout 줄마다 받은 시각을 기록한다."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=cwd, env=env)
    proc.stdin.write(prompt)
    proc.stdin.close()
    lines, t_end = [], time.monotonic() + timeout_s
    for line in proc.stdout:
        lines.append((time.monotonic(), line.rstrip("\n")))
        if time.monotonic() > t_end:
            proc.kill()
            break
    err = proc.stderr.read()
    return proc.wait(), lines, err


def baseline(run: str, root: pathlib.Path | None = None) -> dict:
    """같은 도구·모델·격리 설정에 "OK 만 출력" 을 보내 기본 지시 토큰을 잰다(한 번 재고 저장)."""
    root = root or OBS_DIR
    path = root / BASELINE_FILE
    data = json.loads(path.read_text()) if path.exists() else {}
    if run in data:
        return data[run]
    work = WORK_ROOT / f"baseline-{run}-{datetime.datetime.now():%Y%m%d%H%M%S}"
    (work / "input").mkdir(parents=True)
    (work / "out").mkdir()
    if RUN_MATRIX[run][0] == "codex":
        (work / ".codex_home").mkdir()
        shutil.copy2(pathlib.Path.home() / ".codex" / "auth.json", work / ".codex_home" / "auth.json")
    cmd, env = command(run, work)
    code, lines, _ = _stream(cmd, BASELINE_PROMPT, work, env, 600)
    calls = calls_of(lines, RUN_MATRIX[run][0])
    if code != 0 or not calls:
        raise RuntimeError(f"{run} 기준 측정 실패(종료 {code})")
    data[run] = {"call_input": round(calls[0]["input"]), "measured": datetime.date.today().isoformat(),
                 "model": RUN_MATRIX[run][1]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data[run]


def run_one(case: pathlib.Path, run: str, dry: bool = False, timeout_s: int = 3 * 3600,
            base: dict | None = None) -> dict:
    prompt = build_prompt(case)
    if dry:
        cmd, _ = command(run, WORK_ROOT / "<새 폴더>")
        return {"case": str(case.relative_to(OBS_DIR)), "run": run, "cmd": cmd}
    work = prepare(case, run)
    cmd, env = command(run, work)
    started = datetime.datetime.now()
    t0 = time.monotonic()
    code, lines, err = _stream(cmd, prompt, work, env, timeout_s)
    elapsed = time.monotonic() - t0
    stdout = "\n".join(l for _, l in lines)
    dest = case / run
    dest.mkdir(exist_ok=True)
    (dest / "transcript.jsonl").write_text(stdout + "\n")
    if err:
        (dest / "stderr.txt").write_text(err)
    for name in ("result.json", "worklog.md"):
        src = work / "out" / name
        if src.exists():
            shutil.copy2(src, dest / name)
    extra = sorted(p.name for p in (work / "out").iterdir() if p.name not in ("result.json", "worklog.md"))
    if extra:
        shutil.copytree(work / "out", dest / "out_extra", dirs_exist_ok=True)
    au = audit(stdout, work)
    ms = measure(lines, run, base)
    n = count_results(dest / "result.json")
    tool, model, effort = RUN_MATRIX[run]
    meta = {"run": run, "tool": tool, "model": model, "effort": effort,
            "started": started.isoformat(timespec="seconds"), "wall_sec_including_startup": round(elapsed),
            "exit_code": code, "result_count": n, "measure": ms, "audit": au,
            "workdir": str(work), "extra_outputs": extra}
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    memo = []
    # Claude CLI 는 결과가 성공이어도 종료 코드 1 을 낼 때가 있다(2026-10-10 관찰) → 결과 이벤트로 판정
    if code != 0 and ms["result_ok"] is not True:
        memo.append(f"종료 코드 {code}")
    if n is None:
        memo.append("result.json 없음/깨짐")
    if au["suspect"]:
        memo.append("격리 위반 의심(meta.json audit) — 분석에서 제외 검토")
    wl = dest / "worklog.md"
    if not wl.exists() or "3부" not in wl.read_text():
        memo.append("작업 기록 미완(3부 없음) — 다시 돌리기 검토")
    if ms["pure_input_tokens"] is None:
        memo.append("기준 측정 없음 — 순수 토큰 미계산")
    tokens = (f"순수 입력 {ms['pure_input_tokens']:,} · 출력 {ms['output_tokens']:,}"
              if ms["pure_input_tokens"] is not None else f"출력 {ms['output_tokens']:,}")
    cost = (f"≤{ms['pure_cost_usd_upper']} USD 환산" if ms["pure_cost_usd_upper"] is not None else "단가 미상")
    update_run_sheet(case, run, [
        f"{'Claude Code' if tool == 'claude' else 'Codex CLI'} / {model} / effort {effort}",
        "원본 파일(./input)" + (" + 전사본" if files_in(case / STT_DIR_NAME) else ""),
        started.strftime("%Y-%m-%d %H:%M"),
        f"{ms['pure_sec'] / 60:.1f}분" if ms["pure_sec"] is not None else f"{elapsed / 60:.1f}분(기동 포함)",
        "" if n is None else str(n), f"호출 {ms['calls']}{'(추정)' if ms['calls_estimated'] else ''}",
        f"{tokens} / {cost} (구독 실행)", "; ".join(memo),
    ])
    return meta


def transcribe(case: pathlib.Path) -> list[pathlib.Path]:
    """원본의 음성·영상을 whisper-1 로 한 번 전사해 원본_전사/ 에 둔다(유료). 모든 실행이 같은 전사본을 받는다."""
    sys.path.insert(0, str(ROOT / "api"))
    from dotenv import dotenv_values  # api 가상환경에 있다
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY") or dotenv_values(ROOT / "api" / ".env").get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY 가 없다(api/.env)")
    client = OpenAI(api_key=key)
    out_dir = case / STT_DIR_NAME
    made = []
    for media in files_in(case / "원본"):
        if media.suffix.lower() not in MEDIA_EXT:
            continue
        target = out_dir / f"{media.stem}.txt"
        if target.exists():
            continue
        out_dir.mkdir(exist_ok=True)
        tmp = WORK_ROOT / "stt" / media.stem
        tmp.mkdir(parents=True, exist_ok=True)
        # 16kHz 모노 mp3 로 줄이고 20분 단위로 자른다(파일 상한 25MB)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                        "-b:a", "48k", "-f", "segment", "-segment_time", "1200", str(tmp / "part%03d.mp3")], check=True)
        lines, offset = [], 0.0
        for part in sorted(tmp.glob("part*.mp3")):
            with part.open("rb") as fh:
                res = client.audio.transcriptions.create(model="whisper-1", file=fh,
                                                         response_format="verbose_json", language="ko")
            for seg in res.segments or []:
                s, e = offset + seg.start, offset + seg.end
                lines.append(f"[{int(s // 60):02d}:{s % 60:05.2f} - {int(e // 60):02d}:{e % 60:05.2f}] {seg.text.strip()}")
            offset += float(res.duration or 0)
        target.write_text("\n".join(lines) + "\n")
        made.append(target)
        print(f"전사 {media.name}: {offset / 60:.1f}분 → {target.relative_to(OBS_DIR)} (약 {offset / 60 * 0.006:.3f} USD)")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="할 일 목록만")
    ap.add_argument("--dry-run", action="store_true", help="명령만 출력")
    ap.add_argument("--max", type=int, default=0, help="이번에 돌릴 최대 실행 수(0=전부)")
    ap.add_argument("--only", help="로직·형식 이름 일부로 거르기(예: PROCEDURE, VIDEO)")
    ap.add_argument("--runs", help="쉼표로 실행 이름(기본: 네 개 전부)")
    ap.add_argument("--stt", action="store_true", help="음성·영상 전사 먼저(whisper-1, 유료)")
    args = ap.parse_args(argv)
    runs = args.runs.split(",") if args.runs else None
    for r in runs or []:
        if r not in RUN_MATRIX:
            ap.error(f"모르는 실행 이름: {r} (있는 것: {', '.join(RUN_MATRIX)})")
    todo = pending(only=args.only, runs=runs)
    if args.stt:
        for case in sorted({c for c, _ in todo}):
            transcribe(case)
    if args.list or not todo:
        for case, run in todo:
            print(f"{case.relative_to(OBS_DIR)}  {run}")
        print(f"할 일 {len(todo)}개")
        return 0
    if args.max:
        todo = todo[: args.max]
    bases = {}
    if not args.dry_run:
        for run in sorted({r for _, r in todo}):
            bases[run] = baseline(run)
            print(f"기준 측정 {run}: 기본 지시 {bases[run]['call_input']:,} 토큰/호출")
    for case, run in todo:
        info = run_one(case, run, dry=args.dry_run, base=bases.get(run))
        print(json.dumps(info, ensure_ascii=False) if args.dry_run else
              f"{info['run']:<18} {case.relative_to(OBS_DIR)}  순수 {info['measure']['pure_sec']}s  결과 {info['result_count']}건"
              f"{'  격리 의심' if info['audit']['suspect'] else ''}  종료 {info['exit_code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
