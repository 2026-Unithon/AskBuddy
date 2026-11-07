"""합성 사진·카톡 캡처·글자 PDF 사례를 그린다 (한 번 호출 시험 세트용).

내용·정답은 eval/single_call/rendered_cases.json(합성, 상호 없음). 사진은 실제 폰 사진처럼 기울임·원근·그림자·
흐림·잡티·JPEG 압축을 넣는다 — 깔끔한 그림은 실제보다 쉬운 시험이 된다. 같은 사례는 늘 같은 그림이 나온다(시드 고정).
글자 PDF 는 크롬 headless 인쇄로 만든다(글자층 있음). macOS 글꼴(Apple SD 산돌고딕·애플고딕)을 쓴다.
"""
import json
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
HAND_FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _font(size: int, bold: bool = False, path: str = FONT) -> ImageFont.FreeTypeFont:
    # Apple SD 산돌고딕 ttc 안의 굵기: 0 Regular, 6 Bold 근처. 없으면 0
    try:
        return ImageFont.truetype(path, size, index=6 if bold and path == FONT else 0)
    except OSError:
        return ImageFont.truetype(path, size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > width and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    return out + [cur]


def _paper(case: dict, rng: random.Random) -> Image.Image:
    style = case["style"]
    bg = {"print": (250, 249, 244), "hand": (255, 246, 196), "table": (252, 252, 250),
          "board": (236, 238, 240), "poster": (34, 64, 92)}[style]
    ink = {"board": (30, 70, 160), "poster": (255, 255, 255)}.get(style, (25, 25, 25))
    w, h = (1240, 1500) if style != "hand" else (900, 1000)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    y = 70
    title_font = _font(56 if style == "poster" else 46, bold=True,
                       path=HAND_FONT if style == "hand" else FONT)
    d.text((70, y), case["title"], font=title_font, fill=(200, 40, 40) if style == "board" else ink)
    y += 110
    if style == "hand":
        for ly in range(y, h, 64):
            d.line([(40, ly + 50), (w - 40, ly + 50)], fill=(170, 190, 230), width=2)
    if case.get("table"):
        rows = case["table"]
        cols = [190, 110, 110, 260, 290, 160]
        f = _font(30)
        for r_i, row in enumerate(rows):
            x = 60
            for c_i, cell in enumerate(row):
                d.rectangle([x, y, x + cols[c_i], y + 64], outline=(60, 60, 60), width=2)
                d.text((x + 10, y + 16), cell, font=_font(30, bold=r_i == 0) if r_i == 0 else f, fill=ink)
                x += cols[c_i]
            y += 64
        y += 40
    body = _font(40 if style != "board" else 46, path=HAND_FONT if style == "hand" else FONT)
    for line in case.get("lines", []):
        if style == "hand":
            y = _hand_line(img, line, (60, y), rng) + 64
            continue
        color = ink if style != "board" or rng.random() > 0.3 else (20, 20, 20)
        for part in _wrap(d, line, body, w - 160):
            d.text((80, y), part, font=body, fill=color, stroke_width=1 if style == "board" else 0, stroke_fill=color)
            y += 70 if style != "poster" else 90
    return img


def _hand_line(img: Image.Image, line: str, pos: tuple[int, int], rng: random.Random) -> int:
    """손글씨 흉내: 글자마다 크기·위치·각도를 조금씩 흔든다. {strike:..} 는 쓰고 줄을 긋는다."""
    x, y = pos
    pieces, rest = [], line
    while "{strike:" in rest:
        a, b = rest.split("{strike:", 1)
        s, rest = b.split("}", 1)
        pieces += [(a, False), (s, True)]
    pieces.append((rest, False))
    d = ImageDraw.Draw(img)
    for text, strike in pieces:
        start = x
        for ch in text:
            size = rng.randint(36, 44)
            f = ImageFont.truetype(HAND_FONT, size)
            glyph = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            ImageDraw.Draw(glyph).text((size // 2, size // 2), ch, font=f, fill=(30, 40, 90, 255))
            glyph = glyph.rotate(rng.uniform(-8, 8), resample=Image.BICUBIC)
            img.paste(glyph, (int(x - size // 2), int(y - size // 2 + rng.randint(-4, 4))), glyph)
            x += f.getlength(ch) + rng.randint(-2, 3)
        if strike:
            d.line([(start - 4, y + 22), (x + 4, y + 18)], fill=(30, 40, 90), width=4)
            x += 16
    return y


def _photo(img: Image.Image, rng: random.Random) -> Image.Image:
    """책상 위 종이를 폰으로 찍은 것처럼: 여백·회전·원근·그림자·흐림·잡티."""
    w, h = img.size
    canvas = Image.new("RGB", (int(w * 1.25), int(h * 1.2)), (96, 78, 60))
    canvas.paste(img, (int(w * 0.12), int(h * 0.08)))
    canvas = canvas.rotate(rng.uniform(-3, 3), resample=Image.BICUBIC, expand=False, fillcolor=(96, 78, 60))
    cw, ch = canvas.size
    j = lambda n: rng.randint(0, n)  # noqa: E731
    quad = (j(25), j(15), j(25), ch - j(15), cw - j(25), ch - j(15), cw - j(25), j(15))
    canvas = canvas.transform(canvas.size, Image.QUAD, quad, resample=Image.BICUBIC)
    shade = Image.linear_gradient("L").rotate(rng.choice([0, 90, 180, 270])).resize(canvas.size)
    shade = shade.point(lambda v: 150 + v * 105 // 255).convert("RGB")
    canvas = ImageChops.multiply(canvas, shade)
    canvas = canvas.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.2)))
    noise = Image.effect_noise(canvas.size, 40).convert("RGB")
    canvas = Image.blend(canvas, noise, 0.06)
    return canvas.resize((1500, int(1500 * canvas.size[1] / canvas.size[0])))


def _chat(case: dict) -> Image.Image:
    """카카오톡 대화 캡처 모양. 상대 말풍선 흰색·왼쪽, 내 말풍선 노란색·오른쪽."""
    w, pad = 1080, 40
    f, small, name_f = _font(36), _font(24), _font(28)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    blocks = []
    for m in case["messages"]:
        if "date" in m:
            blocks.append(("date", m, 90))
            continue
        lines = _wrap(probe, m["text"], f, 600)
        blocks.append(("msg", (m, lines), 48 * len(lines) + 40 + (40 if m["who"] != "나" else 0) + 20))
    img = Image.new("RGB", (w, 160 + sum(b[2] for b in blocks)), (155, 187, 212))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 120], fill=(169, 196, 218))
    d.text((pad, 40), "← 사장님", font=_font(40, bold=True), fill=(20, 20, 20))
    y = 150
    for kind, data, height in blocks:
        if kind == "date":
            label = data["date"]
            tw = d.textlength(label, font=small)
            d.rounded_rectangle([(w - tw) / 2 - 24, y + 20, (w + tw) / 2 + 24, y + 62], 20, fill=(140, 170, 195))
            d.text(((w - tw) / 2, y + 27), label, font=small, fill=(255, 255, 255))
        else:
            m, lines = data
            bw = max(d.textlength(line, font=f) for line in lines) + 44
            bh = 48 * len(lines) + 24
            mine = m["who"] == "나"
            if mine:
                x0 = w - pad - bw
                top = y
            else:
                d.ellipse([pad, y, pad + 80, y + 80], fill=(120, 150, 175))
                d.text((pad + 100, y), m["who"], font=name_f, fill=(40, 40, 40))
                x0, top = pad + 100, y + 40
            d.rounded_rectangle([x0, top, x0 + bw, top + bh], 24, fill=(254, 229, 0) if mine else (255, 255, 255))
            for i, line in enumerate(lines):
                d.text((x0 + 22, top + 12 + 48 * i), line, font=f, fill=(20, 20, 20))
            tx = x0 - 120 if mine else x0 + bw + 12
            d.text((tx, top + bh - 30), m["time"], font=small, fill=(80, 90, 100))
        y += height
    return img


def _pdf(case: dict, out: Path) -> None:
    html = ("<html><meta charset='utf-8'><body style=\"font-family:'Apple SD Gothic Neo';font-size:15pt;"
            "line-height:1.7;margin:48px\">" + case["html"] + "</body></html>")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(html, encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", src.as_uri()],
                       check=True, capture_output=True, timeout=60)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"PDF 를 만들지 못했다: {case['case_id']}")


def render_all(spec_path: Path, out: Path) -> None:
    for case in json.loads(spec_path.read_text(encoding="utf-8")):
        case_id = case["case_id"]
        rng = random.Random(case_id)
        case_dir = out / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        if case["format"] == "PHOTO":
            name = "input.jpg"
            _photo(_paper(case, rng), rng).save(case_dir / name, quality=62)
        elif case["format"] == "CHAT_IMAGE":
            name = "input.png"
            _chat(case).save(case_dir / name)
        else:
            name = "input.pdf"
            _pdf(case, case_dir / name)
        meta = {"case_id": case_id, "origin": "synthetic-rendered", "format": case["format"], "logic": case["logic"],
                "input": name, "input_status": "READY"}
        facts = [{"fact_id": f"{case_id}-{i:03d}", **f, "source_key": case_id} for i, f in enumerate(case["facts"], 1)]
        gold = {"case_id": case_id, "judged_by": "claude-synthetic", "judged_at": "2026-11-07", "owner_confirmed": "TEST",
                "note": "합성 자료라 정답을 만든 쪽이 안다. 매장 사실 대비 수치가 아니다", "facts": facts}
        (case_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (case_dir / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
