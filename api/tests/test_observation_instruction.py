"""관찰 지시문 조립(scripts/build_observation_instruction.py) 검사."""
import importlib.util
import pathlib
import unittest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build_observation_instruction.py"
_spec = importlib.util.spec_from_file_location("build_observation_instruction", _PATH)
boi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boi)


class BuildObservationInstructionTest(unittest.TestCase):
    def test_all_logics_and_formats_present(self):
        self.assertEqual(boi.logics(), ["NOTICE", "POLICY", "PROCEDURE", "RECIPE", "REFERENCE"])
        self.assertEqual(boi.formats(), ["AUDIO", "CHAT", "DOC_IMAGE", "DOC_TEXT", "OWNER_TEXT", "VIDEO"])

    def test_every_combination_fills_every_placeholder(self):
        for logic in boi.logics():
            for fmt in boi.formats():
                with self.subTest(logic=logic, fmt=fmt):
                    text = boi.build(logic, fmt)
                    self.assertNotIn("{{", text)
                    self.assertIn("━━ 1부. 작업 기록", text)
                    self.assertIn("━━ 2부. 추출 결과 (JSON)", text)
                    self.assertIn("━━ 3부. 자기 점검", text)

    def test_recipe_doc_image_keeps_original_rules(self):
        # 예전 레시피·PDF/PNG 지시문의 핵심 규칙이 그대로 나와야 한다(회귀 기준)
        text = boi.build("RECIPE", "DOC_IMAGE")
        for needle in [
            "판매가 · 제조순서 · 컵 · 샷 수",
            "블렌더 회전수 · 우리는 시간 · 1펌프 용량",
            "범위(\"225~275ml\")로 합치지 마세요",
            "물 8부 (425ml)",
            "읽히지 않는 값을 추정해서 채우지 마세요",
            "사실 하나에 값 하나입니다",
            "특정 영역을 잘라 확대",
            "\"pages_or_images\"",
            "표·목록 행 수와 뽑은 행 수가 맞는가",
            "같은 표의 모든 행이 같은 속성 집합",
        ]:
            self.assertIn(needle, text)

    def test_logic_and_format_specific_parts_differ(self):
        proc_video = boi.build("PROCEDURE", "VIDEO")
        self.assertIn("\"timing\"", proc_video)
        self.assertIn("\"kind\": \"TIME\"", proc_video)
        self.assertIn("말과 화면이 서로 다른 곳", proc_video)
        notice_chat = boi.build("NOTICE", "CHAT")
        self.assertIn("\"valid_until\"", notice_chat)
        self.assertIn("\"kind\": \"DATE\"", notice_chat)

    def test_unknown_names_rejected(self):
        with self.assertRaises(ValueError):
            boi.build("MENU", "DOC_TEXT")
        with self.assertRaises(ValueError):
            boi.build("RECIPE", "PDF")

    def test_built_instructions_match_sources(self):
        # 지시문/ 폴더의 30개가 부록·공통 본문과 어긋나면 실패한다(고친 뒤 --build-all 로 다시 만든다)
        for logic, _ in boi.LOGIC_ORDER:
            for fmt, _ in boi.FORMAT_ORDER:
                with self.subTest(logic=logic, fmt=fmt):
                    path = boi.built_path(logic, fmt)
                    self.assertTrue(path.exists(), f"{path} 없음 — --build-all 실행")
                    self.assertEqual(path.read_text(), boi.build(logic, fmt))

    def test_order_lists_cover_all_appendices(self):
        self.assertEqual(sorted(k for k, _ in boi.LOGIC_ORDER), boi.logics())
        self.assertEqual(sorted(k for k, _ in boi.FORMAT_ORDER), boi.formats())

    def test_owner_text_has_paste_slots(self):
        text = boi.build("POLICY", "OWNER_TEXT")
        self.assertIn("직원 질문: (여기에 직원 질문을 붙여넣으세요)", text)
        self.assertIn("점주 답변: (여기에 점주 답변을 붙여넣으세요)", text)

    def test_scaffold_creates_slots_without_overwriting(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            made = boi.scaffold(root)
            case = root / "02_PROCEDURE_업무절차" / "04_VIDEO_영상" / "자료1"
            self.assertTrue((case / "원본").is_dir())
            self.assertEqual((case / "지시문.md").read_text(), boi.build("PROCEDURE", "VIDEO"))
            for run in boi.RUN_IDS:
                self.assertTrue((case / run / "result.json").exists())
                self.assertTrue((case / run / "worklog.md").exists())
                self.assertTrue((case / run / "captures").is_dir())
            self.assertEqual(len(made), 1 + 30 * (2 + 2 * len(boi.RUN_IDS)))
            self.assertEqual((root / "README.md").read_text(), (boi.TEMPLATE_DIR / "관찰_README.md").read_text())
            (case / boi.RUN_IDS[0] / "result.json").write_text('{"results": []}')
            self.assertEqual(boi.scaffold(root), [])
            self.assertEqual((case / boi.RUN_IDS[0] / "result.json").read_text(), '{"results": []}')

    def test_parse_sections_ignores_preamble(self):
        self.assertEqual(boi.parse_sections("# 제목\n설명\n## a\n하나\n\n## b\n둘\n"), {"a": "하나", "b": "둘"})


if __name__ == "__main__":
    unittest.main()
