"""Lyric FX for Beat For Speed - animated, colourful lyrics with no game code changes.

The game shows each lyric entry with its own colour, size and position. This tool "bakes"
animation into the lyric data: one line becomes a quick sequence of entries, so it can
type in word by word, pop, pulse on the beat, shimmer through colours, fade out, dissolve
word by word, or shrink away. Works on ANY chart that has lyrics (made by hand, by the
editor's Lyrics Assistant, by make_chart.py or the AI director) and in the unmodified game.

Re-running is safe: the original lyrics are kept in the chart under "lyricFxSource" and the
effects are always rebuilt from those. Use --strip to restore the plain lyrics.

  python lyric_fx.py chart.json                       # preset "auto" -> chart_lyricfx.json
  python lyric_fx.py chart.json --preset party -o out.json
  python lyric_fx.py chart.json --strip               # remove effects again

Presets: auto (mixes effects by line role), karaoke, party, chill, glitch, clean.
"""
import argparse
import colorsys
import json
import os
import random
import re
from collections import Counter

FRAME_S = 0.07            # ~14 steps per second: smooth enough, keeps entry counts sane
NBSP = " "
DARK = "#000000"


# ---------------------------------------------------------------- colour helpers

def hex_to_rgb(value):
    value = (value or "#ffffff").lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def mix(a, b, t):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def shift_hue(color, degrees, lighten=0.0):
    h, l, s = colorsys.rgb_to_hls(*hex_to_rgb(color))
    if s < 0.08:                     # near-white/grey: give it some colour so shimmer is visible
        s, l = 0.6, min(l, 0.75)
    return rgb_to_hex(colorsys.hls_to_rgb((h + degrees / 360) % 1, min(1, l + lighten), s))


def brighten(color, amount=0.18):
    h, l, s = colorsys.rgb_to_hls(*hex_to_rgb(color))
    return rgb_to_hex(colorsys.hls_to_rgb(h, min(1, l + amount), s))


PALETTES = {
    "party": ["#ff4fa3", "#ffc94f", "#4fffd2", "#7c94ff", "#ff7a4f"],
    "chill": ["#bfe8ff", "#e6e0ff", "#d6ffe9", "#ffe6f2"],
    "glitch": ["#00ffd5", "#ff00a8", "#ffffff", "#b6ff00"],
}


# ---------------------------------------------------------------- effect building blocks

class Line:
    def __init__(self, entry, bpm, words=None):
        self.entry = entry
        self.bps = bpm / 60.0
        self.start = entry["beat"] / self.bps
        self.end = (entry["beat"] + entry["duration"]) / self.bps
        self.text = entry["text"]
        self.words = self.text.split()
        self.color = entry.get("color") or "#ffffff"
        self.size = int(entry.get("size") or 40)
        self.word_times = words  # optional [(start_s, end_s)] per word from forced alignment


def frame(line, t0, t1, **over):
    e = {k: v for k, v in line.entry.items() if k not in ("beat", "duration", "text", "color", "size")}
    e["beat"] = round(t0 * line.bps, 4)
    e["duration"] = round(max(0.01, (t1 - t0) * line.bps), 4)
    e["text"] = over.get("text", line.text)
    e["color"] = over.get("color", line.color)
    e["size"] = int(max(12, min(120, over.get("size", line.size))))
    if "position" in over:
        e["position"] = over["position"]
    return e


def padded(words, shown, hidden_style="pad"):
    """Show the first `shown` words; keep the rest as invisible padding so the line doesn't jump."""
    visible = " ".join(words[:shown])
    rest = " ".join(words[shown:])
    if not rest or hidden_style != "pad":
        return visible
    return (visible + " " + NBSP * len(rest)) if visible else NBSP * len(rest)


def enter_frames(line, kind, budget):
    """Frames from line.start; returns (frames, end_time)."""
    t, out = line.start, []
    if kind == "type" and len(line.words) > 1:
        if line.word_times and len(line.word_times) == len(line.words):
            times = [max(line.start, w[0]) for w in line.word_times]
        else:  # spread by word length over up to 70% of the line
            span = min(budget, (line.end - line.start) * 0.7)
            weights = [len(w) + 1 for w in line.words]
            acc, times = 0, []
            for w in weights:
                times.append(line.start + span * acc / sum(weights))
                acc += w
        for i, t0 in enumerate(times):
            t1 = times[i + 1] if i + 1 < len(times) else max(t0 + FRAME_S, times[-1] + 0.12)
            if t1 > t0:
                out.append(frame(line, t0, t1, text=padded(line.words, i + 1)))
        return out, out[-1]["beat"] / line.bps + out[-1]["duration"] / line.bps if out else line.start
    if kind == "pop":
        for scale in (1.35, 1.18, 1.06):
            out.append(frame(line, t, t + FRAME_S, size=line.size * scale, color=brighten(line.color, 0.15)))
            t += FRAME_S
        return out, t
    if kind == "fade":
        steps = 4
        for i in range(steps):
            out.append(frame(line, t, t + FRAME_S, color=mix(DARK, line.color, (i + 1) / (steps + 1))))
            t += FRAME_S
        return out, t
    return out, t


def exit_frames(line, kind, start, rng):
    """Frames ending at line.end, starting at `start`."""
    t, out = start, []
    if kind == "fade":
        steps = 5
        for i in range(steps):
            out.append(frame(line, t, t + FRAME_S, color=mix(line.color, DARK, (i + 1) / (steps + 1))))
            t += FRAME_S
    elif kind == "dissolve" and len(line.words) > 1:
        order = list(range(len(line.words)))
        rng.shuffle(order)
        remaining = list(line.words)
        for i in order[:-1]:
            remaining[i] = NBSP * len(line.words[i])
            out.append(frame(line, t, t + FRAME_S * 1.3, text=" ".join(remaining), color=mix(line.color, DARK, 0.25)))
            t += FRAME_S * 1.3
    elif kind == "shrink":
        for scale in (0.85, 0.7, 0.55):
            out.append(frame(line, t, t + FRAME_S, size=line.size * scale, color=mix(line.color, DARK, 0.3)))
            t += FRAME_S
    elif kind == "glitch":
        for i in range(4):
            garbled = "".join(c if rng.random() > 0.35 or c == " " else rng.choice("#%&*@!?/\\") for c in line.text)
            out.append(frame(line, t, t + FRAME_S, text=garbled, color=PALETTES["glitch"][i % 4]))
            t += FRAME_S
    return out


def exit_length(kind, line):
    return {"fade": 5 * FRAME_S, "dissolve": max(0, len(line.words) - 1) * FRAME_S * 1.3,
            "shrink": 3 * FRAME_S, "glitch": 4 * FRAME_S}.get(kind, 0)


def hold_frames(line, kind, t0, t1, palette, beat_s):
    if t1 - t0 <= FRAME_S:
        return []
    if kind == "pulse":   # brighter flash on every beat
        out, t = [], t0
        while t < t1 - 1e-6:
            flash = min(t1, t + min(0.12, beat_s * 0.3))
            out.append(frame(line, t, flash, color=brighten(line.color, 0.22), size=line.size * 1.04))
            nxt = min(t1, t + beat_s)
            if nxt > flash:
                out.append(frame(line, flash, nxt))
            t = nxt
        return out
    if kind == "shimmer":  # colour walks through the palette, one step per half beat
        out, t, i = [], t0, 0
        while t < t1 - 1e-6:
            nxt = min(t1, t + beat_s / 2)
            color = palette[i % len(palette)] if palette else shift_hue(line.color, 25 * i)
            out.append(frame(line, t, nxt, color=color))
            t, i = nxt, i + 1
        return out
    if kind == "breathe":  # gentle size swell over two beats
        out, t, i = [], t0, 0
        while t < t1 - 1e-6:
            nxt = min(t1, t + beat_s / 2)
            out.append(frame(line, t, nxt, size=line.size * (1.0, 1.04, 1.07, 1.04)[i % 4]))
            t, i = nxt, i + 1
        return out
    return [frame(line, t0, t1)]


# ---------------------------------------------------------------- presets

def choose(preset, line, role, rng):
    """(enter, hold, exit) for one line."""
    if preset == "clean":
        return "none", "none", "none"
    if preset == "karaoke":
        return "type", "none", "fade"
    if preset == "chill":
        return "fade", "breathe" if role == "chorus" else "none", "fade"
    if preset == "party":
        return rng.choice(["pop", "type"]), rng.choice(["pulse", "shimmer"]), rng.choice(["dissolve", "shrink", "fade"])
    if preset == "glitch":
        return "pop", "shimmer", "glitch"
    # auto: role-based
    if role == "chorus":
        return "pop", "pulse", "dissolve"
    if role == "short":
        return "pop", "none", "shrink"
    if role == "outro":
        return "fade", "breathe", "fade"
    return "type", "none", "fade"


def bake(chart, preset="auto", seed=7, words_by_line=None):
    source = chart.get("lyricFxSource") or chart.get("lyrics") or []
    if not source:
        raise SystemExit("chart has no lyrics")
    bpm = float(chart["musicData"]["bpm"])
    beat_s = 60.0 / bpm
    rng = random.Random(seed)
    normalized = Counter(re.sub(r"[^\w]+", " ", l["text"].lower()).strip() for l in source)
    palette = PALETTES.get(preset)
    out = []
    last_index = len(source) - 1
    for idx, entry in enumerate(sorted(source, key=lambda l: l["beat"])):
        line = Line(entry, bpm, (words_by_line or {}).get(round(entry["beat"], 2)))
        key = re.sub(r"[^\w]+", " ", line.text.lower()).strip()
        role = "chorus" if normalized[key] >= 2 else "short" if len(line.words) <= 2 else "outro" if idx >= last_index - 1 else "verse"
        enter, hold, leave = choose(preset, line, role, rng)
        length = line.end - line.start
        if length < 0.45:                       # too short to animate: keep it plain
            out.append(frame(line, line.start, line.end))
            continue
        frames, t = enter_frames(line, enter, budget=length * 0.6)
        exit_len = min(exit_length(leave, line), max(0, line.end - t) * 0.5)
        exit_start = line.end - exit_len
        frames += hold_frames(line, hold, t, exit_start, palette, beat_s)
        if exit_len > 0:
            ex = exit_frames(line, leave, exit_start, rng)
            if ex:  # squeeze to fit exactly
                scale = exit_len / sum(f["duration"] / line.bps for f in ex)
                t = exit_start
                for f in ex:
                    d = f["duration"] / line.bps * scale
                    f["beat"], f["duration"] = round(t * line.bps, 4), round(max(0.01, d * line.bps), 4)
                    t += d
                frames += ex
        # never spill past the line's own end (the next line on this row starts there)
        end_beat = entry["beat"] + entry["duration"]
        trimmed = []
        for f in sorted(frames, key=lambda f: f["beat"]):
            if f["beat"] >= end_beat - 1e-4:
                continue
            f["duration"] = round(min(f["duration"], end_beat - f["beat"]), 4)
            if trimmed and f["beat"] <= trimmed[-1]["beat"] + 0.01:
                trimmed.pop()                    # same start: the later frame wins
            elif trimmed and f["beat"] < trimmed[-1]["beat"] + trimmed[-1]["duration"]:
                trimmed[-1]["duration"] = round(f["beat"] - trimmed[-1]["beat"], 4)
            trimmed.append(f)
        out += trimmed or [frame(line, line.start, line.end)]
    result = json.loads(json.dumps(chart))
    result["lyricFxSource"] = source
    result["lyrics"] = out
    return result


def load_words(path, bpm):
    """Optional word timings (lyrics_words.json from make_chart.py), keyed by line start beat."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        lines = json.load(fh)
    return {round(l["start"] * bpm / 60.0, 2): [(w["start"], w["end"]) for w in l.get("words", [])] for l in lines}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chart")
    ap.add_argument("--preset", default="auto", choices=["auto", "karaoke", "party", "chill", "glitch", "clean"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--words", help="word timings json (default: lyrics_words.json next to the chart, if present)")
    ap.add_argument("--strip", action="store_true", help="restore the original, un-animated lyrics")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    with open(args.chart, encoding="utf-8") as fh:
        chart = json.load(fh)
    base, ext = os.path.splitext(args.chart)
    if args.strip:
        if chart.get("lyricFxSource"):
            chart["lyrics"] = chart.pop("lyricFxSource")
        out_path = args.out or base + "_plain" + ext
    else:
        words = load_words(args.words or os.path.join(os.path.dirname(os.path.abspath(args.chart)), "lyrics_words.json"),
                           float(chart["musicData"]["bpm"]))
        chart = bake(chart, args.preset, args.seed, words)
        out_path = args.out or base + "_lyricfx" + ext
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(chart, fh, ensure_ascii=False)
    src = len(chart.get("lyricFxSource") or chart.get("lyrics") or [])
    print(json.dumps({"preset": None if args.strip else args.preset, "lines": src, "entries": len(chart["lyrics"]), "out": out_path}))


if __name__ == "__main__":
    main()
