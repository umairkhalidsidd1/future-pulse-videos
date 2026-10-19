"""Bright, bold YouTube thumbnail (1280x720) made from a video frame + 2-4 huge words."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter

from .config import ASSETS


def _frame(video: Path, out: Path, at: float = 0.5) -> Image.Image:
    seek = ["-ss", f"{at:.2f}"] if at > 0 else []          # seeking inside a photo gives no frame at all
    out.unlink(missing_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(video), "-frames:v", "1", "-update", "1", str(out)],
                   check=False)
    if out.exists():
        return Image.open(out).convert("RGB")
    return Image.new("RGB", (1280, 720), (15, 32, 39))


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap(words: list[str], font, max_w: int, draw) -> list[str]:
    lines, cur = [], ""
    for wd in words:
        test = f"{cur} {wd}".strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = wd
    lines.append(cur)
    return lines


def make(video: Path, text: str, out: Path, badge: str = "TOP 5 TODAY", accent=(255, 230, 0), at: float = 0.5):
    W, H = 1280, 720
    img = _cover(_frame(video, out.with_suffix(".frame.png"), at), W, H)
    img = ImageEnhance.Color(img).enhance(1.5)
    img = ImageEnhance.Contrast(img).enhance(1.2)

    # Dark gradient on the left so the text pops.
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=int(max(0, 210 - x * 0.25)))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shade)

    draw = ImageDraw.Draw(img)
    font_path = str(ASSETS / "fonts" / "Anton-Regular.ttf")
    words = text.upper().split()
    size, lines = 230, []
    while size > 70:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(words, font, int(W * 0.66), draw)
        line_h = int(size * 1.08)
        if len(lines) <= 3 and line_h * len(lines) <= H * 0.72:
            break
        size -= 10
    font = ImageFont.truetype(font_path, size)
    line_h = int(size * 1.08)
    y = (H - line_h * len(lines)) // 2 + 30
    for i, line in enumerate(lines):
        fill = accent if i % 2 == 0 else (255, 255, 255)
        draw.text((60, y), line, font=font, fill=fill, stroke_width=max(6, size // 18), stroke_fill=(0, 0, 0))
        y += line_h

    if badge:
        bfont = ImageFont.truetype(font_path, 54)
        bw = int(draw.textlength(badge, font=bfont)) + 48
        draw.rounded_rectangle((50, 40, 50 + bw, 120), radius=14, fill=(230, 30, 40))
        draw.text((74, 46), badge, font=bfont, fill=(255, 255, 255))

    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=60))
    img.save(out, "JPEG", quality=90)
    return out
