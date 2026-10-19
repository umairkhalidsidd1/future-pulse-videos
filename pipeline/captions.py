"""Word-by-word animated captions (ASS subtitle file). Word times come from align.py."""
import re
from pathlib import Path

from .config import CFG


# ---------- ASS file ----------

def _color(hex_rgb: str, alpha: str = "00") -> str:
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _groups(words: list[dict], max_words: int, max_chars: int) -> list[list[dict]]:
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or sum(len(x["w"]) + 1 for x in cur) + len(w["w"]) > max_chars
                    or w["scene"] != cur[-1]["scene"] or w["s"] - cur[-1]["e"] > 0.35):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?,;:]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[dict], path: Path, *, width: int, height: int, vertical: bool, theme: dict,
              total: float, overlays: list[dict], progress_bar: bool = False):
    """Big-channel style captions: 1-3 words, the spoken word pops bigger in colour, key words coloured,
    thick outline + shadow, a small tilt per group. overlays: [{"text", "start", "end", "style"}]."""
    c = CFG["captions"]
    font, hook_font = c["font"], c.get("hook_font", c["font"])
    white, hi, key = _color(theme["text"]), _color(theme["highlight"]), _color(theme["keyword"])
    black, shadow = "&H00000000", "&H64000000"
    if vertical:
        cap = f"Style: Cap,{font},96,{white},{white},{black},{shadow},0,0,0,0,100,100,0,0,1,9,6,5,50,50,0,1"
        hook = (f"Style: Hook,{hook_font},128,&H00000000,&H00000000,{hi},{shadow},0,0,0,0,100,100,1,0,3,20,0,8,"
                f"70,70,300,1")
        tag = f"Style: Tag,{hook_font},60,{white},{white},{black},{shadow},0,0,0,0,100,100,1,0,1,5,2,8,60,60,200,1"
        max_words, max_chars, cap_y = 3, 14, int(height * 0.63)
    else:
        cap = f"Style: Cap,{font},64,{white},{white},{black},{shadow},0,0,0,0,100,100,0,0,1,6,4,2,160,160,70,1"
        hook = (f"Style: Hook,{hook_font},150,&H00000000,&H00000000,{hi},{shadow},0,0,0,0,100,100,1,0,3,22,0,5,"
                f"160,160,0,1")
        tag = f"Style: Tag,{hook_font},64,&H00000000,&H00000000,{hi},{hi},0,0,0,0,100,100,0,0,3,14,0,7,70,70,60,1"
        max_words, max_chars, cap_y = 5, 30, None

    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding", cap, hook, tag, "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    if progress_bar:  # a bar across the top that fills up: viewers see how short the video is and stay
        h, ms = 14, int(total * 1000)
        bar = f"m 0 0 l {width} 0 {width} {h} 0 {h}"
        lines.append(f"Dialogue: 3,{_ts(0)},{_ts(total)},Cap,,0,0,0,,{{\\an7\\pos(0,0)\\bord0\\shad0"
                     f"\\c{hi}\\clip(0,0,1,{h})\\t(0,{ms},\\clip(0,0,{width},{h}))\\p1}}{bar}{{\\p0}}")

    for o in overlays:
        text = _esc(o["text"]).replace("\n", "\\N")
        pop = "{\\fad(60,120)\\fscx60\\fscy60\\t(0,120,\\fscx108\\fscy108)\\t(120,200,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 2,{_ts(o['start'])},{_ts(o['end'])},{o['style']},,0,0,0,,{pop}{text}")

    pos = f"\\an5\\pos({width // 2},{cap_y})" if cap_y else ""
    groups = _groups(words, max_words, max_chars)
    for gi, g in enumerate(groups):
        next_start = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else total
        g_end = min(g[-1]["e"] + 0.25, next_start, total)
        tilt = f"\\frz{(-2, 0, 2, 1, -1)[gi % 5]}" if vertical else ""
        for i, w in enumerate(g):
            start = w["s"]
            end = g[i + 1]["s"] if i + 1 < len(g) else g_end
            if end <= start:
                continue
            parts = []
            for j, x in enumerate(g):
                t = _esc(x["w"].upper() if vertical else x["w"])
                if j == i:  # the word being spoken: highlight colour + a quick bounce
                    bounce = ("\\fscx112\\fscy112\\t(0,70,\\fscx126\\fscy126)\\t(70,150,\\fscx118\\fscy118)"
                              if vertical else "")
                    parts.append(f"{{\\c{hi}{bounce}}}{t}{{\\c{white}\\fscx100\\fscy100}}")
                elif x["key"]:
                    parts.append(f"{{\\c{key}}}{t}{{\\c{white}}}")
                else:
                    parts.append(t)
            pop = "\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)" if (i == 0 and vertical) else ""
            lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{{pos}{tilt}{pop}}}" + " ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
