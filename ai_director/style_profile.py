"""Learn how human charters use non-note events, from Steam Workshop charts on disk.

Produces a compact profile (rates per minute, alignment habits, a few example event
timelines) that is sent to Claude as style guidance. Nothing here calls the API.
"""
import glob
import json
import os
import re
import statistics

NOTE_TYPES = {"spawn_cube", "spawn_sting", "spawn_jiucai"}


def classify(datamodel):
    name = datamodel.split("/")[-1]
    if name in NOTE_TYPES or "rise" in name:
        return "note"
    if re.match(r"^(color_|city_|coast_|mountain_|bright_|ghost$)", name):
        return "theme"
    if name in ("spawn_third", "spawn_first", "spawn_third_bb"):
        return "camera"
    if name.startswith("speed_"):
        return "speed"
    return {"spawn_thunder": "thunder", "spawn_ramp": "ramp", "spawn_wheelie": "wheelie",
            "spawn_dog_crossing": "dog_crossing", "screen_flash": "screen_fx",
            "screen_glitch": "screen_fx", "screen_breath": "screen_fx"}.get(name, "other")


def density(notes, beat, before):
    lo, hi = (beat - 8, beat) if before else (beat, beat + 8)
    return sum(1 for b in notes if lo <= b < hi) / 8.0  # notes per beat


def analyze_chart(chart):
    ents = chart.get("entities") or []
    bpm = float((chart.get("musicData") or {}).get("bpm") or 120)
    notes = sorted(float(e["beat"]) for e in ents if classify(e.get("datamodel", "")) == "note")
    if len(notes) < 50:
        return None
    minutes = (notes[-1] - notes[0]) * 60 / bpm / 60
    events = sorted(
        ((float(e["beat"]), classify(e.get("datamodel", "")), e["datamodel"].split("/")[-1]) for e in ents
         if classify(e.get("datamodel", "")) not in ("note", "other")),
        key=lambda x: x[0])
    result = {"bpm": bpm, "minutes": round(minutes, 2), "track": (chart.get("musicData") or {}).get("trackId"),
              "counts": {}, "on_phrase": 0, "density_shift": 0, "events": len(events), "timeline": []}
    for beat, kind, name in events:
        result["counts"][kind] = result["counts"].get(kind, 0) + 1
        if min(beat % 16, 16 - beat % 16) <= 0.5:
            result["on_phrase"] += 1
        before, after = density(notes, beat, True), density(notes, beat, False)
        if abs(after - before) >= 0.4 or (before > 0 and abs(after - before) / before >= 0.5):
            result["density_shift"] += 1
        result["timeline"].append(f"{beat:.0f}:{name}({before:.1f}->{after:.1f}n/b)")
    return result


def build_profile(workshop_dir, max_examples=3):
    charts = []
    for path in glob.glob(os.path.join(workshop_dir, "*", "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("entities"):
            info = analyze_chart(data)
            if info and info["events"] >= 4:
                charts.append(info)
    if not charts:
        return None
    kinds = sorted({k for c in charts for k in c["counts"]})
    rates = {}
    for kind in kinds:
        per_min = [c["counts"].get(kind, 0) / max(c["minutes"], 0.5) for c in charts]
        used = [r for r in per_min if r > 0]
        rates[kind] = {"charts_using": f"{len(used)}/{len(charts)}",
                       "median_per_min_when_used": round(statistics.median(used), 2) if used else 0}
    total = sum(c["events"] for c in charts)
    examples = sorted(charts, key=lambda c: -len(c["counts"]))[:max_examples]
    return {
        "charts_analyzed": len(charts),
        "rates": rates,
        "share_on_16_beat_phrase": round(sum(c["on_phrase"] for c in charts) / total, 2),
        "share_at_density_shift": round(sum(c["density_shift"] for c in charts) / total, 2),
        "example_timelines": [
            {"bpm": c["bpm"], "track": c["track"], "minutes": c["minutes"], "events": c["timeline"][:40]}
            for c in examples
        ],
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(build_profile(sys.argv[1]), indent=1, ensure_ascii=False))
