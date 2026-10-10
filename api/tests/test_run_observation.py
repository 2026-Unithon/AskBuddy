"""Phase 0 관찰 실행기(scripts/run_observation.py) 검사. 실제 CLI·모델은 부르지 않는다."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_observation.py"
_spec = importlib.util.spec_from_file_location("run_observation", _PATH)
ro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ro)

_BOI_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build_observation_instruction.py"
_bspec = importlib.util.spec_from_file_location("build_observation_instruction", _BOI_PATH)
boi = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(boi)


class RunObservationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "관찰"
        boi.scaffold(self.root)
        self.case = self.root / "04_REFERENCE_매장정보" / "01_DOC_TEXT_문서글자" / "자료1"

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_names_match_scaffold_folders(self):
        self.assertEqual(list(ro.RUN_MATRIX), boi.RUN_IDS)

    def test_pending_needs_original_and_empty_result(self):
        self.assertEqual(ro.pending(self.root), [])
        (self.case / "원본" / "memo.txt").write_text("자료")
        (self.case / "원본" / ".DS_Store").write_text("x")
        got = ro.pending(self.root)
        self.assertEqual([r for _, r in got], list(ro.RUN_MATRIX))
        (self.case / "claude-opus-5.5" / "result.json").write_text('{"results": []}')
        self.assertNotIn((self.case, "claude-opus-5.5"), ro.pending(self.root))
        self.assertEqual(ro.pending(self.root, runs=["gpt-luna-6.0"]), [(self.case, "gpt-luna-6.0")])
        self.assertEqual(ro.pending(self.root, only="PROCEDURE"), [])

    def test_owner_text_waits_for_question(self):
        owner = self.root / "03_POLICY_운영규칙" / "06_OWNER_TEXT_점주답변" / "자료1"
        (owner / "원본" / "a.jpg").write_bytes(b"x")
        self.assertEqual(ro.pending(self.root, only="OWNER_TEXT"), [])
        p = owner / "지시문.md"
        p.write_text(p.read_text().replace(ro.OWNER_PLACEHOLDER, "환불 돼요?"))
        self.assertEqual(len(ro.pending(self.root, only="OWNER_TEXT")), 4)

    def test_prompt_is_instruction_plus_same_suffix(self):
        base = (self.case / "지시문.md").read_text().rstrip()
        p1 = ro.build_prompt(self.case)
        self.assertTrue(p1.startswith(base))
        self.assertIn("./out/result.json", p1)
        self.assertIn("인터넷을 쓰지 마세요", p1)
        self.assertNotIn("_전사", p1)
        (self.case / ro.STT_DIR_NAME).mkdir()
        (self.case / ro.STT_DIR_NAME / "a.txt").write_text("[00:00.00 - 00:01.00] 안녕")
        self.assertIn("./input/_전사/", ro.build_prompt(self.case))

    def test_commands_isolate_environment(self):
        work = pathlib.Path("/tmp/askbuddy-observe/x")
        with mock.patch.dict(ro.os.environ, {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "a", "CODEX_BIN": "/bin/codex"}):
            cmd, env = ro.command("claude-sonnet-5.5", work)
            self.assertIn("--setting-sources", cmd)
            self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "local")
            self.assertIn("--strict-mcp-config", cmd)
            self.assertIn("WebSearch", cmd)
            self.assertEqual(cmd[cmd.index("--model") + 1], "claude-sonnet-5-5")
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            cmd, env = ro.command("gpt-sol-6.1", work)
            self.assertEqual(cmd[0], "/bin/codex")
            for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"):
                self.assertIn(flag, cmd)
            self.assertEqual(env["CODEX_HOME"], str(work / ".codex_home"))
            self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-6.1-sol")

    def test_audit_flags_outside_paths_and_network(self):
        work = pathlib.Path("/tmp/askbuddy-observe/run1")
        ok = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "input": {"command": "python3 -c 'print(1)' /tmp/askbuddy-observe/run1/input/a.pdf"}}]}})
        self.assertFalse(ro.audit(ok, work)["suspect"])
        bad = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "input": {"command": "cat /Users/someone/repo/추출결과/old.json"}}]}})
        self.assertTrue(ro.audit(bad, work)["suspect"])
        net = json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "curl https://x"}})
        self.assertEqual(ro.audit(net, work)["network"], ["curl", "https://"])
        # 모델의 말(텍스트)에 경로가 나와도 도구 입력이 아니면 세지 않는다
        talk = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "/Users/x 는 안 읽음"}]}})
        self.assertFalse(ro.audit(talk, work)["suspect"])

    def test_measure_subtracts_harness_and_startup(self):
        ev = lambda t, d: (t, json.dumps(d))
        lines = [
            ev(0.0, {"type": "system", "subtype": "init"}),
            ev(1.0, {"type": "assistant", "message": {"id": "m1", "usage": {
                "input_tokens": 5, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 39000, "output_tokens": 50}}}),
            ev(1.5, {"type": "assistant", "message": {"id": "m1", "usage": {
                "input_tokens": 5, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 39000, "output_tokens": 50}}}),
            ev(9.0, {"type": "assistant", "message": {"id": "m2", "usage": {
                "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 45000, "output_tokens": 100}}}),
            ev(10.0, {"type": "result", "num_turns": 2, "total_cost_usd": 0.9}),
        ]
        m = ro.measure(lines, "claude-sonnet-5.5", {"call_input": 38000})
        self.assertEqual(m["calls"], 2)                      # 같은 메시지 id 는 한 번만
        self.assertEqual(m["raw_input_tokens"], 85005)
        self.assertEqual(m["pure_input_tokens"], 2005 + 7000)
        self.assertEqual(m["output_tokens"], 150)
        self.assertEqual(m["pure_sec"], 10.0)
        self.assertAlmostEqual(m["pure_cost_usd_upper"], (9005 * 2 + 150 * 10) / 1e6, places=4)
        self.assertIsNone(ro.measure(lines, "claude-sonnet-5.5", None)["pure_input_tokens"])

    def test_measure_codex_estimates_calls(self):
        ev = lambda t, d: (t, json.dumps(d))
        lines = [
            ev(2.0, {"type": "thread.started"}),
            ev(3.0, {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}}),
            ev(4.0, {"type": "item.completed", "item": {"type": "command_execution", "command": "cat a"}}),
            ev(6.0, {"type": "turn.completed", "usage": {"input_tokens": 60000, "output_tokens": 300,
                                                          "reasoning_output_tokens": 200}}),
        ]
        m = ro.measure(lines, "gpt-luna-6.0", {"call_input": 14000})
        self.assertEqual(m["calls"], 3)
        self.assertTrue(m["calls_estimated"])
        self.assertEqual(m["pure_input_tokens"], 60000 - 3 * 14000)
        self.assertEqual(m["output_tokens"], 500)
        self.assertEqual(m["pure_sec"], 4.0)
        self.assertIsNone(m["pure_cost_usd_upper"])          # GPT 단가는 모름

    def test_run_sheet_row_replaced(self):
        ro.update_run_sheet(self.case, "gpt-luna-6.0", ["a", "b", "c", "d", "e", "f", "g", "h"])
        text = (self.case / "RUN_SHEET.md").read_text()
        self.assertIn("| gpt-luna-6.0 | a | b | c | d | e | f | g | h |", text)
        self.assertEqual(text.count("| gpt-luna-6.0 |"), 1)

    def test_run_one_copies_outputs_without_cli(self):
        (self.case / "원본" / "memo.txt").write_text("와이파이 비밀번호 1234")
        work_root = pathlib.Path(self.tmp.name) / "work"

        def fake_stream(cmd, prompt, cwd, env, timeout_s):
            self.assertEqual(sorted(p.name for p in (pathlib.Path(cwd) / "input").iterdir()), ["memo.txt"])
            self.assertIn("./out/result.json", prompt)
            (pathlib.Path(cwd) / "out" / "result.json").write_text('{"meta": {}, "results": [{"fact_id": "f-0001"}]}')
            (pathlib.Path(cwd) / "out" / "worklog.md").write_text("1부")
            lines = [(0.0, json.dumps({"type": "system", "subtype": "init"})),
                     (5.0, json.dumps({"type": "assistant", "message": {"id": "a", "usage": {
                         "input_tokens": 40000, "output_tokens": 10}}})),
                     (6.0, json.dumps({"type": "result", "num_turns": 1}))]
            return 0, lines, ""

        with mock.patch.object(ro, "OBS_DIR", self.root), mock.patch.object(ro, "WORK_ROOT", work_root), \
                mock.patch.object(ro, "_stream", side_effect=fake_stream):
            meta = ro.run_one(self.case, "claude-sonnet-5.5", base={"call_input": 38000})
        self.assertEqual(meta["result_count"], 1)
        self.assertEqual(meta["measure"]["pure_input_tokens"], 2000)
        self.assertEqual(meta["measure"]["pure_sec"], 6.0)
        dest = self.case / "claude-sonnet-5.5"
        self.assertEqual((dest / "worklog.md").read_text(), "1부")
        sheet = (self.case / "RUN_SHEET.md").read_text()
        self.assertIn("| claude-sonnet-5.5 | Claude Code / claude-sonnet-5-5", sheet)
        self.assertIn("순수 입력 2,000 · 출력 10", sheet)


if __name__ == "__main__":
    unittest.main()
