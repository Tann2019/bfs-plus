"""AI chart director for Beat For Speed.

Takes a chart made by chart_pipeline/make_chart.py (timing from the game's own generator, notes
from the instrumental, aligned lyrics) and asks Claude to direct it like a rhythm-game designer:
lane patterns and density per phrase, obstacle-car patterns, the scene and its colour themes,
camera / speed / ramp / thunder moments, and lyric colour / position / size.

Claude only returns a plan (strict JSON schema, valid options only). Deterministic code applies
the plan to the beat-accurate notes and enforces playability, then a flow checker scores the
chart before and after. Spend is capped by budget.Ledger (default $30 total).

  python director.py "<chart folder made by make_chart.py>" --difficulty 2
  python director.py <chart dir> --dry-run        # free: token count + worst-case cost only
"""
import argparse
import json
import math
import os
import subprocess
import re
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "chart_pipeline"))
sys.path.insert(0, HERE)
import make_chart as mc  # noqa: E402
from budget import BudgetExceeded, Ledger  # noqa: E402
from style_profile import build_profile  # noqa: E402

MODEL = "claude-opus-5-5"
WORKSHOP_DIR = mc.paths.workshop_dir()
SCENES = ["city", "forest", "coast", "mountain"]
SCENE_GROUP = {"city": "City Theme", "forest": "Forest Theme", "coast": "Coast Theme", "mountain": "Mountain Theme"}
LANE_PATTERNS = ["keep", "melody", "wave", "zigzag", "stairs", "wide_alternate", "center", "call_response", "diagonal", "sweep"]
DENSITIES = {"sparse": 0.45, "light": 0.7, "normal": 1.0, "dense": 1.3, "max": 1.6}
CAR_PATTERNS = ["none", "few", "gates", "slalom", "walls", "between"]
FOLLOW = ["generator", "drums", "kick_snare", "melody", "vocals", "mix"]
DOUBLES = ["none", "accents", "big_hits"]
BONUS = ["none", "downbeats", "drop_hits"]
EVENT_EXCLUDE = {"spawn_cube", "spawn_sting", "spawn_jiucai", "hit_sound_volume", "spawn_cutpoint", "spawn_dog_crossing"}
CUBE = "custom_custom_spawn_cube/spawn_cube"
CAR = "custom_custom_spawn_cube/spawn_sting"
BONUS_CUBE = "custom_spawn_jiucai/spawn_jiucai"
DOUBLE_SHARE_MAX = {"accents": 0.05, "big_hits": 0.08}   # of a phrase's cubes
DOUBLE_GLOBAL_MAX = 0.04                                  # of all cubes in the song
BONUS_SHARE_MAX = 0.04


def log(msg):
    print(f"[director] {msg}", flush=True)


def load_env():
    for path in (os.path.join(ROOT, ".env"), os.path.join(HERE, ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                match = re.match(r"^\s*([A-Z_]+)\s*=\s*\"?([^\"\r\n]+?)\"?\s*$", line)
                if match and not os.environ.get(match.group(1)):
                    os.environ[match.group(1)] = match.group(2)


# ---------------------------------------------------------------- audio features

def frames(path, hop_s=0.05):
    signal = mc.load_mono(path)
    hop = int(mc.ANALYSIS_RATE * hop_s)
    n = len(signal) // hop
    block = signal[: n * hop].reshape(n, hop)
    rms = np.sqrt((block ** 2).mean(axis=1) + 1e-12)
    log_rms = np.log(rms + 1e-5)
    flux = np.maximum(0, np.diff(log_rms, prepend=log_rms[0]))
    return signal, rms, flux, hop_s


def spectral_centroid(signal, hop_s=0.05, n_fft=2048):
    hop = int(mc.ANALYSIS_RATE * hop_s)
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / mc.ANALYSIS_RATE)
    out = []
    for start in range(0, len(signal) - n_fft, hop):
        mag = np.abs(np.fft.rfft(signal[start:start + n_fft] * window))
        total = mag.sum()
        out.append(float((mag * freqs).sum() / total) if total > 1e-6 else 0.0)
    return np.array(out)


def peaks(flux, hop_s, percentile=80, min_gap_s=0.1):
    threshold = np.percentile(flux, percentile)
    idx = [i for i in range(1, len(flux) - 1) if flux[i] > threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    kept = []
    for i in idx:
        if kept and (i - kept[-1]) * hop_s < min_gap_s:
            if flux[i] > flux[kept[-1]]:
                kept[-1] = i
            continue
        kept.append(i)
    return np.array(kept) * hop_s, flux[kept] if kept else np.array([])


def band_flux(signal, lo, hi, hop_s=0.01, n_fft=1024):
    """Onset flux of one frequency band (e.g. kick 30-150 Hz, snare 180-4000 Hz) at 10 ms frames."""
    hop = int(mc.ANALYSIS_RATE * hop_s)
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / mc.ANALYSIS_RATE)
    band = (freqs >= lo) & (freqs < hi)
    n = max(0, (len(signal) - n_fft) // hop)
    energy = []
    for chunk in range(0, n, 2000):  # chunked STFT keeps memory small
        rows = np.arange(chunk, min(n, chunk + 2000))
        idx = np.arange(n_fft)[None, :] + hop * rows[:, None]
        spec = np.abs(np.fft.rfft(signal[idx] * window, axis=1))
        energy.append(spec[:, band].sum(axis=1))
    log_e = np.log(np.concatenate(energy) + 1e-6) if energy else np.zeros(1)
    return np.maximum(0, np.diff(log_e, prepend=log_e[0])), hop_s


class Features:
    def __init__(self, stems_dir):
        _, self.inst_rms, self.inst_flux, self.hop = frames(os.path.join(stems_dir, "no_vocals.wav"))
        drum_signal, self.drum_rms, self.drum_flux, _ = frames(os.path.join(stems_dir, "drums.wav"))
        vocal_signal, self.vocal_rms, _, _ = frames(os.path.join(stems_dir, "vocals.wav"))
        other_signal, self.other_rms, _, _ = frames(os.path.join(stems_dir, "other.wav"))
        log("analyzing melody pitch (spectral centroid of the 'other' stem)...")
        self.centroid = spectral_centroid(other_signal, self.hop)
        self.drum_hits, _ = peaks(self.drum_flux, self.hop)
        self.inst_hits, self.inst_hit_strength = peaks(self.inst_flux, self.hop)
        loud = self.vocal_rms[self.vocal_rms > np.percentile(self.vocal_rms, 50)]
        self.vocal_threshold = max(0.01, float(np.percentile(loud, 20)) if len(loud) else 0.02)
        log("finding kick / snare / melody / vocal hits...")
        self.hits = {}   # name -> (times, strengths), 10 ms resolution
        for name, signal, lo, hi, pct in (("kick", drum_signal, 30, 150, 85), ("snare", drum_signal, 180, 4000, 85),
                                          ("melody", other_signal, 150, 5000, 85), ("vocal", vocal_signal, 150, 4000, 80)):
            flux, hop = band_flux(signal, lo, hi)
            times, strength = peaks(flux, hop, percentile=pct, min_gap_s=0.09)
            if name == "vocal":  # only syllables while the singer is actually audible
                keep = np.array([self.at(self.vocal_rms, t) > self.vocal_threshold for t in times], dtype=bool)
                times, strength = (times[keep], strength[keep]) if len(times) else (times, strength)
            if len(strength):
                strength = strength / (np.percentile(strength, 95) + 1e-9)
            self.hits[name] = (times, strength)

    def at(self, arr, t):
        i = int(t / self.hop)
        return float(arr[min(max(i, 0), len(arr) - 1)])

    def pitch(self, t):
        i = int(t / self.hop)
        window = self.centroid[max(0, i - 1): i + 2]
        return float(window.mean()) if len(window) else 0.0

    def onset_strength(self, t):
        i = int(t / self.hop)
        return float(max(self.inst_flux[max(0, i - 1): i + 2].max(initial=0), self.drum_flux[max(0, i - 1): i + 2].max(initial=0)))


# ---------------------------------------------------------------- exact tempo

def fit_tempo(feats, nominal_bpm):
    """The song's real tempo and where its bars start, from the strong kicks/snares of the drum stem.
    The game's generator rounds the tempo (e.g. 128 instead of 127.70); over a 3-minute song that drifts
    notes by a third of a beat. Returns (bpm, first downbeat in seconds, consistency 0-1)."""
    kick_times, kick_strength = feats.hits["kick"]
    strong = kick_times[kick_strength >= 0.6]
    if len(strong) < 16:
        return nominal_bpm, 0.0, 0.0
    best = (0.0, nominal_bpm, 0.0)
    for bpm in np.arange(nominal_bpm - 2.0, nominal_bpm + 2.0, 0.005):
        period = 60.0 / bpm
        mean = np.exp(2j * np.pi * strong / period).mean()
        if abs(mean) > best[0]:
            best = (abs(mean), float(bpm), float(np.angle(mean) / (2 * np.pi) * period) % period)
    consistency, bpm, phase = best
    if consistency < 0.6:        # no steady kick to lock to: keep the generator's tempo
        return nominal_bpm, 0.0, round(float(consistency), 2)
    period = 60.0 / bpm
    snare_times, snare_strength = feats.hits["snare"]
    snares = snare_times[snare_strength >= 0.6]
    def backbeat_score(shift):   # snares land on beats 2 and 4 of the bar
        beats = np.round((snares - phase) / period).astype(int) - shift
        return np.isin(beats % 4, (1, 3)).sum()
    shift = max(range(4), key=backbeat_score) if len(snares) else 0
    return round(bpm, 2), round(phase + shift * period, 4), round(float(consistency), 2)   # the editor keeps 2 decimals


def retime_chart(chart, new_bpm, offset_s):
    """Move a chart onto the grid of new_bpm whose beat 0 is the first downbeat (offset_s seconds).
    Generator cubes are snapped to the 16th grid of the real tempo."""
    old_bpm = float(chart["musicData"]["bpm"])
    to_grid = lambda beat: (float(beat) * 60.0 / old_bpm - offset_s) * new_bpm / 60.0
    for entity in chart.get("entities", []):
        entity["beat"] = round(round(to_grid(entity["beat"]) * 4) / 4, 4)
    for line in chart.get("lyrics") or []:
        end = to_grid(line["beat"] + line.get("duration", 0))
        line["beat"] = round(to_grid(line["beat"]), 4)
        line["duration"] = round(max(0.05, end - line["beat"]), 4)
    for segment in (chart.get("editorMeta", {}).get("songStructure") or {}).get("segments") or []:
        for key in ("start_beat", "end_beat"):
            if key in segment:
                segment[key] = round(to_grid(segment[key]), 4)
    chart["musicData"]["bpm"] = new_bpm
    chart["musicData"]["offset"] = 0


def to_absolute_beats(chart, offset_s):
    """Write beats as absolute song time (seconds * bpm / 60) with musicData.offset = 0, so the timing is
    right however the game treats the offset field."""
    offset_beats = offset_s * float(chart["musicData"]["bpm"]) / 60.0
    for entity in chart.get("entities", []):
        entity["beat"] = round(float(entity["beat"]) + offset_beats, 4)
    for line in chart.get("lyrics") or []:
        line["beat"] = round(float(line["beat"]) + offset_beats, 4)
    chart["musicData"]["offset"] = 0


def write_aligned_audio(source, destination, pad_s):
    """The song with pad_s seconds of silence in front (OGG), so its first downbeat lands on a whole beat."""
    import soundfile
    rate = soundfile.info(source).samplerate   # (the ffmpeg the game ships has no ffprobe)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
                    "-af", f"adelay=delays={int(round(pad_s * rate))}S:all=1", "-c:a", "libvorbis", "-q:a", "6", destination],
                   check=True)


def shift_features(feats, offset_s):
    """Make feature times relative to the first downbeat (so beat b is at b * beat length)."""
    for name, (times, strength) in feats.hits.items():
        feats.hits[name] = (times - offset_s, strength)
    feats.drum_hits = feats.drum_hits - offset_s
    feats.inst_hits = feats.inst_hits - offset_s
    frames_to_drop = int(round(offset_s / feats.hop))
    if frames_to_drop > 0:
        for name in ("inst_rms", "inst_flux", "drum_rms", "drum_flux", "vocal_rms", "other_rms", "centroid"):
            setattr(feats, name, getattr(feats, name)[frames_to_drop:])


def find_drops(rows, feats, bpm):
    """Bars where the beat slams back in: loud, the kick is back, and the bar(s) before were a build or a
    gap (kick missing or much quieter). One drop per 8 bars at most."""
    beat_s = 60.0 / bpm
    kick_times, kick_strength = feats.hits["kick"]
    strong = kick_times[kick_strength >= 0.5]
    kicks = [int(((strong >= r["bar"] * 4 * beat_s) & (strong < (r["bar"] + 1) * 4 * beat_s)).sum()) for r in rows]
    drops, last = [], -99
    for index, row in enumerate(rows):
        if index < 2 or index - last < 8:
            continue
        before_energy = max(rows[index - 1]["energy"], rows[index - 2]["energy"])
        kick_returned = kicks[index] >= 3 and min(kicks[index - 1], kicks[index - 2]) <= 1
        energy_jump = row["energy"] - before_energy >= 3
        if row["energy"] >= 6 and kicks[index] >= 3 and (kick_returned or energy_jump):
            drops.append(index)
            last = index
    return drops


# ---------------------------------------------------------------- chart helpers

def kind(entity):
    return entity.get("datamodel", "").split("/")[-1]


def split_chart(chart):
    axis = chart.get("editorMeta", {}).get("axisMap") or [0] * len(chart["entities"])
    cubes, cars, others = [], [], []
    for entity, ax in zip(chart["entities"], axis):
        if ax == 0 and kind(entity) in ("spawn_cube", "spawn_jiucai"):
            cubes.append(dict(entity))
        elif ax == 0 and kind(entity) == "spawn_sting":
            cars.append(dict(entity))
        else:
            others.append((dict(entity), ax))
    return cubes, cars, others


def bar_table(chart, feats, bpm, total_beats):
    beat_s = 60.0 / bpm
    cubes, cars, _ = split_chart(chart)
    segments = (chart.get("editorMeta", {}).get("songStructure") or {}).get("segments") or []
    inst_rank = np.argsort(np.argsort(feats.inst_rms))
    n_bars = int(math.ceil(total_beats / 4))
    rows = []
    for bar in range(n_bars):
        b0, b1 = bar * 4, bar * 4 + 4
        t0, t1 = b0 * beat_s, b1 * beat_s
        i0, i1 = int(t0 / feats.hop), max(int(t0 / feats.hop) + 1, int(t1 / feats.hop))
        energy = int(min(9, inst_rank[i0:i1].mean() / len(inst_rank) * 10)) if i0 < len(inst_rank) else 0
        drums = int(((feats.drum_hits >= t0) & (feats.drum_hits < t1)).sum())
        vocal = float((feats.vocal_rms[i0:i1] > feats.vocal_threshold).mean()) if i0 < len(feats.vocal_rms) else 0.0
        pitch = feats.centroid[i0:i1]
        section = next((s.get("label", "") for s in segments if s["start_beat"] <= b0 < s["end_beat"]), "")
        rows.append({
            "bar": bar, "beat": b0, "time": round(t0, 1), "energy": energy, "drumHits": drums,
            "vocal": round(vocal, 1), "melodyHz": int(pitch.mean()) if len(pitch) else 0,
            "cubes": sum(1 for c in cubes if b0 <= c["beat"] < b1), "cars": sum(1 for c in cars if b0 <= c["beat"] < b1),
            "section": section,
        })
    return rows


def rhythm_grid(feats, bpm, n_bars):
    """Per bar, a 16-step string per instrument: X strong hit, x hit, . nothing (16th-note grid)."""
    step_s = 60.0 / bpm / 4
    grids = []
    for bar in range(n_bars):
        row = {}
        for name in ("kick", "snare", "melody", "vocal"):
            times, strength = feats.hits[name]
            cells = []
            for step in range(16):
                t = (bar * 16 + step) * step_s
                near = np.abs(times - t) <= 0.06 if len(times) else np.array([], dtype=bool)
                s = strength[near].max() if near.any() else 0
                cells.append("X" if s >= 0.6 else "x" if s > 0 else ".")
            row[name] = "".join(cells)
        grids.append(row)
    return grids


def note_grid(chart, bpm, n_bars):
    """What the chart actually contains, per bar: 16 steps showing the lane (5-9), D double, b bonus, c car."""
    beat_s = 60.0 / bpm
    axis = chart.get("editorMeta", {}).get("axisMap") or [0] * len(chart["entities"])
    cells = [["."] * 16 for _ in range(n_bars)]
    by_step = {}
    for e, ax in zip(chart["entities"], axis):
        if ax != 0:
            continue
        step = int(round(float(e["beat"]) * 4))
        bar, pos = divmod(step, 16)
        if bar >= n_bars:
            continue
        by_step.setdefault((bar, pos), []).append(e)
    for (bar, pos), ents in by_step.items():
        cubes = [e for e in ents if kind(e) in ("spawn_cube", "spawn_jiucai")]
        if len(cubes) >= 2:
            cells[bar][pos] = "D"
        elif cubes and kind(cubes[0]) == "spawn_jiucai":
            cells[bar][pos] = "b"
        elif cubes:
            cells[bar][pos] = str(cubes[0].get("key", 7))
        elif any(kind(e) == "spawn_sting" for e in ents):
            cells[bar][pos] = "c"
    return ["".join(row) for row in cells]


# ---------------------------------------------------------------- prompt

DESIGN_GUIDE = """You are the lead chart designer for "Beat For Speed", a rhythm driving game. The player drives
down a 5-lane road (lanes 5,6,7,8,9 left to right). Cubes are collected by steering into their lane on the beat;
obstacle cars (each covers about 2 lanes) must be avoided. The scene (city, forest, coast, mountain) sets the
track; colour-theme events recolour the scene mid-song; camera and speed events change the feel.

Design like the best rhythm games do:
- Beat Saber: notes should FLOW. Movement between consecutive notes should feel like a dance - smooth sweeps,
  waves and alternations, not random jumps. Fast passages use small lateral moves; big moves get time.
  Patterns repeat when the music repeats (same riff = same pattern), and change when the music changes.
- Guitar Hero: lanes follow the music. Rising melody moves right, falling moves left ("melody" pattern follows
  the lead instrument's pitch). Note density follows what is actually playing - sparse verses, busy choruses.
- Shape the whole song: intro eases in, verses breathe, pre-choruses build, the drop/chorus is the payoff
  (densest, widest movement, cars, speed-up, theme change), breakdowns give rest. Give the player recovery
  moments after hard sections. Difficulty should ramp, not spike.
- Obstacle cars add tension in high-energy sections; keep them readable (gates and slaloms that guide the
  player along the note path), never in quiet intros, and never so dense the road feels blocked.
- Visual events land on musical moments: theme changes on section boundaries and drops (not every few bars),
  camera switches sparingly to mark big moments, speed-ups for the most intense sections and back to normal
  after. Thunder fits dark/stormy themes and hard hits. A ramp is a launch on a big hit right before a pause
  or into a drop (its flight removes notes for 2-8 beats). A favourite touch (use it when the song has a
  clear big drop, not every time): launch a ramp on the hit leading into the biggest drop so the player lands
  exactly as the drop hits - set the flight so it ends on the drop's first downbeat. Other ramps are rare.
- Lyrics: style them to the song's mood - chorus lines bigger and in an accent colour, verses calmer, move
  position (top/middle/bottom) between sections for variety, use row 2 for echoes/backing lines. Colours must
  read well over the chosen scene/themes (bright on dark themes). Keep it tasteful.

DROPS are the payoff and must land exactly. Bars marked DROP in the analysis are where the beat slams back
in (measured from the drum stem). The drop starts on the FIRST BEAT of that bar - not a bar early, not a bar
late: start a phrase exactly at that bar, put the theme change / speed-up / camera switch on its first beat,
land any ramp so its flight ends on that beat, make that phrase the densest and widest of its section with
accents (bonus "drop_hits", doubles "big_hits" for the biggest one) and cars. The bars just before a drop
(the build) should tighten and rise toward it; a 1-bar near-rest right before the drop makes it hit harder.

Your plan is applied by code: timing always comes from the audio analysis; you choose patterns per phrase.
Lane patterns: keep (generator's lanes), melody (follow pitch), wave (smooth 5->9->5 sweeps), zigzag
(6/8 alternation with 7 on downbeats), stairs (ascending runs), wide_alternate (5/9 - only for slow, big hits),
center (lanes 6-8, calm), call_response (alternate sides every bar), diagonal (quick notes become one-lane-
per-note diagonal runs - fun on fast fills and 16th-note hooks), sweep (slow notes swing edge to edge,
left to right - pair it with cars "between").

What the game's own official charts do (measured over its 25 built-in songs) - match this house style:
- Quick notes (< 0.2 s apart) mostly move one lane (53%) or stay (31%); diagonal runs are everywhere.
- Slow notes (>= 0.6 s apart) often jump wide (3+ lanes in 40%), and about a third of those have an
  obstacle car between them to dodge while crossing.
- About 9% of bars are empty: rests are normal. When the music drops out, let the chart drop out too.
- Cars are common: roughly 0.6 cars per cube overall, more in energetic sections.
Follow (what the notes are placed on in that phrase): generator (the game's beat model), drums (kick+snare+
other drum hits), kick_snare (only the backbone: great for drops, very readable), melody (the lead synth/
instrument rhythm - builds and hooks), vocals (sung syllables, Guitar Hero vocal style - good for verses and
catchy chorus lines), mix (strongest hits of anything). Pick what the listener is most likely tapping along to.
Density: sparse/light/normal/dense/max relative to the followed part's hits.
Doubles (two cubes at once, both must be collected): use SPARINGLY - "accents" marks only a few of the very
biggest hits in a phrase, "big_hits" a few more for the biggest drop; most phrases should be "none". Code caps
doubles at a few percent of notes and never puts them in fast runs.
Bonus cubes (extra score, no combo break): "downbeats" or "drop_hits" in a few climactic phrases, else "none".
Cars: none, few, gates (pairs leaving the note lane open), slalom (alternating sides), walls (several cars,
one open path), between (a car in the lanes crossed between two slow far-apart notes). Phrases must cover every bar from 0 to the last bar with no overlaps, usually 4-8 bars each,
split at section changes.
Events: use only the provided datamodels; param = flight beats for a ramp (2-8), wheelie length in beats,
0 otherwise. Place exactly one level_end at the end of the music.
"""


def build_prompt(chart, rows, lyrics_lines, scene, difficulty, style, catalog, grids=None):
    allowed = []
    for t in catalog:
        name = t["datamodel"].split("/")[-1]
        if t["group"] == "Common" and name not in EVENT_EXCLUDE:
            allowed.append(t)
        elif t["group"] in SCENE_GROUP.values() and (scene is None or t["group"] == SCENE_GROUP[scene]):
            allowed.append(t)
    catalog_text = "\n".join(f"- {t['datamodel']} [{t['group']}] {t['label']}: {t['description']}" for t in allowed)
    style_text = json.dumps({k: style[k] for k in ("charts_analyzed", "rates", "share_at_density_shift")}) if style else "n/a"
    system = DESIGN_GUIDE + "\nEvent datamodels you may use:\n" + catalog_text + \
        "\n\nHow human charters in this game's Steam Workshop use events (rates per minute):\n" + style_text
    bpm = chart["musicData"]["bpm"]
    table = "bar|beat|time_s|energy0-9|drumHits|vocal0-1|melodyHz|cubes|cars|section|DROP\n" + "\n".join(
        f"{r['bar']}|{r['beat']}|{r['time']}|{r['energy']}|{r['drumHits']}|{r['vocal']}|{r['melodyHz']}|{r['cubes']}|{r['cars']}|{r['section']}|{'DROP' if r.get('drop') else ''}"
        for r in rows)
    lyric_text = "\n".join(f"{i}|{l['time']:.1f}s|beat {l['beat']:.1f}|{l['text']}" for i, l in enumerate(lyrics_lines)) or "(no lyrics)"
    grid_text = ""
    if grids:
        grid_text = ("\n\nRhythm per bar on a 16th-note grid (X strong hit, x hit, . none). K=kick S=snare M=melody V=vocal:\n"
                     + "\n".join(f"{i}|K {g['kick']}|S {g['snare']}|M {g['melody']}|V {g['vocal']}" for i, g in enumerate(grids)))
    user = (
        f"Song BPM {bpm}, {len(rows)} bars, difficulty {difficulty}/4 "
        f"({'player chooses' if scene is None else 'scene fixed to ' + scene}).\n"
        "The cube/car counts show the game generator's current draft.\n\n"
        f"Per-bar analysis:\n{table}{grid_text}\n\nLyric lines (index|time|beat|text):\n{lyric_text}\n\n"
        "Direct this chart: choose the scene, plan every phrase (including what its notes follow), place events, "
        "and style each lyric line."
    )
    return system, user, allowed


def plan_schema(allowed, n_lyrics, scene):
    datamodels = [t["datamodel"] for t in allowed]
    obj = lambda props: {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}
    return obj({
        "scene": {"type": "string", "enum": [scene] if scene else SCENES},
        "summary": {"type": "string"},
        "phrases": {"type": "array", "items": obj({
            "startBar": {"type": "integer"}, "endBar": {"type": "integer"}, "label": {"type": "string"},
            "intensity": {"type": "integer"}, "lanePattern": {"type": "string", "enum": LANE_PATTERNS},
            "follow": {"type": "string", "enum": FOLLOW},
            "density": {"type": "string", "enum": list(DENSITIES)}, "cars": {"type": "string", "enum": CAR_PATTERNS},
            "doubles": {"type": "string", "enum": DOUBLES}, "bonus": {"type": "string", "enum": BONUS},
            "reason": {"type": "string"}})},
        "events": {"type": "array", "items": obj({
            "beat": {"type": "number"}, "datamodel": {"type": "string", "enum": datamodels},
            "param": {"type": "number"}, "reason": {"type": "string"}})},
        "lyrics": {"type": "array", "items": obj({
            "index": {"type": "integer"}, "color": {"type": "string"},
            "position": {"type": "string", "enum": ["top", "middle", "bottom"]},
            "size": {"type": "integer"}, "row": {"type": "integer"}})},
    })


# ---------------------------------------------------------------- applying the plan

def lane_sequence(pattern, notes, feats, beat_s):
    n = len(notes)
    if pattern == "keep" or n == 0:
        return [int(x.get("key", 7)) for x in notes]
    if pattern == "melody":
        pitch = np.array([feats.pitch(x["beat"] * beat_s) for x in notes])
        if pitch.max() - pitch.min() < 1:
            return [7] * n
        ranks = np.argsort(np.argsort(pitch)) / max(1, n - 1)
        return [5 + int(round(r * 4)) for r in ranks]
    if pattern == "wave":
        cycle = [5, 6, 7, 8, 9, 8, 7, 6]
        return [cycle[i % len(cycle)] for i in range(n)]
    if pattern == "zigzag":
        return [7 if abs(x["beat"] % 4) < 1e-6 else (6 if i % 2 == 0 else 8) for i, x in enumerate(notes)]
    if pattern == "stairs":
        return [(5 if (i // 4) % 2 == 0 else 6) + i % 4 for i in range(n)]
    if pattern == "wide_alternate":
        return [5 if i % 2 == 0 else 9 for i in range(n)]
    if pattern == "center":
        return [7 if abs(x["beat"] % 2) < 1e-6 else (6 if i % 2 == 0 else 8) for i, x in enumerate(notes)]
    if pattern == "diagonal":
        # quick notes (< 0.2 s apart) run one lane per note; each run goes the way there is room,
        # alternating direction run to run; slower notes reset toward the side the next run starts from
        lanes, lane, direction = [], 7, 1
        for i, x in enumerate(notes):
            gap_beats = x["beat"] - notes[i - 1]["beat"] if i else 9
            fast = i > 0 and (gap_beats <= 0.5 + 1e-6 or gap_beats * beat_s < 0.2)  # 8ths or faster
            if fast:
                if not 5 <= lane + direction <= 9:
                    direction = -direction
                lane += direction
            else:
                direction = -direction
                lane = 6 if direction > 0 else 8
            lanes.append(lane)
        return lanes
    if pattern == "sweep":
        # slow notes swing edge to edge (left-to-right feel); anything quick in between steps toward
        # the next edge instead of jumping
        lanes, target, lane = [], 5, 7
        for i, x in enumerate(notes):
            gap = (x["beat"] - notes[i - 1]["beat"]) * beat_s if i else 9
            if gap >= 0.45:
                target = 9 if target == 5 else 5
                lane = target
            else:
                lane += 1 if target > lane else -1 if target < lane else 0
            lanes.append(lane)
        return lanes
    if pattern == "call_response":
        return [(5 + i % 2) if int(x["beat"] // 4) % 2 == 0 else (8 + i % 2) for i, x in enumerate(notes)]
    return [int(x.get("key", 7)) for x in notes]


def smooth_flow(cubes, beat_s, fast_s=0.25, max_jump=2):
    """No impossible moves: within fast_s of the previous cube, move at most max_jump lanes."""
    for prev, cur in zip(cubes, cubes[1:]):
        if (cur["beat"] - prev["beat"]) * beat_s < fast_s and abs(cur["key"] - prev["key"]) > max_jump:
            cur["key"] = prev["key"] + max_jump * (1 if cur["key"] > prev["key"] else -1)
        cur["key"] = min(9, max(5, cur["key"]))


def car_conflict(car, cubes, beat_s, same_lane_s=0.2, adjacent_s=0.12):
    """Calibrated on the game's official charts: cars sit >= ~0.2 s from a cube in the same lane and
    >= ~0.1 s from one in a neighbouring lane (5th percentiles), so allow that close, not closer."""
    for c in cubes:
        dt = abs(c["beat"] - car["beat"]) * beat_s
        lanes = abs(c["key"] - car["key"])
        if (lanes == 0 and dt < same_lane_s) or (lanes == 1 and dt < adjacent_s):
            return True
    return False


def make_cars(pattern, b0, b1, cubes, beat_s):
    def lane_near(beat):
        future = [c for c in cubes if c["beat"] >= beat]
        return future[0]["key"] if future else 7
    cars = []
    if pattern == "few":
        for beat in np.arange(b0 + 2, b1, 4):
            lane = 5 if lane_near(beat) >= 7 else 9
            cars.append({"beat": float(beat), "key": lane})
    elif pattern == "gates":
        for beat in np.arange(b0 + 1, b1, 2):
            path = lane_near(beat)
            cars += [{"beat": float(beat), "key": lane} for lane in (5, 9) if abs(lane - path) >= 2]
    elif pattern == "slalom":
        for i, beat in enumerate(np.arange(b0 + 1, b1, 1)):
            cars.append({"beat": float(beat), "key": 5 if i % 2 == 0 else 9})
    elif pattern == "between":
        # a car in the lanes you cross between two slow, far-apart notes: time the crossing
        ordered = sorted(cubes, key=lambda c: c["beat"])
        for a, b in zip(ordered, ordered[1:]):
            if b0 <= a["beat"] < b1 and (b["beat"] - a["beat"]) * beat_s >= 0.6 and abs(b["key"] - a["key"]) >= 2:
                mid_beat = round((a["beat"] + b["beat"]) / 2 * 4) / 4
                cars.append({"beat": float(mid_beat), "key": int(round((a["key"] + b["key"]) / 2))})
    elif pattern == "walls":
        for beat in np.arange(b0 + 2, b1, 2):
            path = lane_near(beat)
            cars += [{"beat": float(beat), "key": lane} for lane in (5, 7, 9) if abs(lane - path) >= 2]
    return [dict(c, datamodel=CAR, width=0.25, volume=100) for c in cars]


def add_accents(cubes, phrases, feats, beat_s):
    """Doubles and bonus cubes, deliberately rare: per-phrase share caps, a global cap, only on the
    strongest hits, and doubles only where there is room before and after (never inside fast runs)."""
    total = len(cubes)
    double_budget = int(total * DOUBLE_GLOBAL_MAX)
    bonus_budget = int(total * BONUS_SHARE_MAX)
    strength = lambda c: feats.onset_strength(c["beat"] * beat_s) * (1.5 if abs(c["beat"] % 1) < 1e-6 else 1.0)
    extra = []
    for p in phrases:
        mine = [c for c in cubes if c.get("_phrase") == id(p)]
        if not mine:
            continue
        mode = p.get("doubles", "none")
        if mode in DOUBLE_SHARE_MAX and double_budget > 0:
            roomy = []
            for i, c in enumerate(cubes):
                if c.get("_phrase") != id(p):
                    continue
                prev_gap = (c["beat"] - cubes[i - 1]["beat"]) * beat_s if i > 0 else 9
                next_gap = (cubes[i + 1]["beat"] - c["beat"]) * beat_s if i + 1 < len(cubes) else 9
                if prev_gap >= 0.4 and next_gap >= 0.4:
                    roomy.append(c)
            count = min(double_budget, max(1, int(len(mine) * DOUBLE_SHARE_MAX[mode])))
            for c in sorted(roomy, key=strength, reverse=True)[:count]:
                # Doubles sit in ADJACENT lanes (e.g. 6+7). Lean toward where the next note goes,
                # otherwise toward the centre; edge lanes can only pair inward.
                i = cubes.index(c)
                nxt = cubes[i + 1]["key"] if i + 1 < len(cubes) else 7
                side = 1 if nxt > c["key"] else -1 if nxt < c["key"] else (1 if c["key"] < 7 else -1)
                partner = c["key"] + side
                if partner < 5 or partner > 9:
                    partner = c["key"] - side
                extra.append({**c, "key": partner})
                double_budget -= 1
        mode = p.get("bonus", "none")
        if mode != "none" and bonus_budget > 0:
            if mode == "downbeats":
                picks = [c for c in mine if abs(c["beat"] % 8) < 1e-6]
            else:
                picks = [mine[0]] + sorted(mine[1:], key=strength, reverse=True)[:2]
            for c in picks[:max(1, min(bonus_budget, 4))]:
                c["datamodel"] = BONUS_CUBE
                bonus_budget -= 1
    return sorted(cubes + extra, key=lambda c: (c["beat"], c["key"]))


def apply_plan(chart, plan, feats, difficulty, catalog_by_dm):
    bpm = float(chart["musicData"]["bpm"])
    beat_s = 60.0 / bpm
    cubes, cars, others = split_chart(chart)
    end_beat = max([c["beat"] for c in cubes + cars] + [0]) + 4
    grid = 0.5 if difficulty <= 2 else 0.25
    spacing = 0.5 if difficulty <= 1 else (0.375 if difficulty == 2 else 0.25)
    new_cubes, new_cars, notes_report = [], [], []
    phrases = sorted(plan["phrases"], key=lambda p: p["startBar"])
    covered = set()
    for p in phrases:
        b0, b1 = max(0, p["startBar"]) * 4, (max(p["startBar"], p["endBar"]) + 1) * 4
        if b0 in covered:
            continue
        covered.add(b0)
        draft = sorted([c for c in cubes if b0 <= c["beat"] < b1], key=lambda c: c["beat"])
        ratio = DENSITIES.get(p["density"], 1.0)
        follow = p.get("follow", "generator")
        target = int(round((len(draft) if draft else (b1 - b0) / 2) * ratio))
        weight = lambda beat: 1.6 if abs(beat % 1) < 1e-6 else 1.25 if abs(beat % 0.5) < 1e-6 else 1.0
        pool = {}  # snapped beat -> score
        def add(beat, score):
            if b0 <= beat < b1:
                pool[beat] = max(pool.get(beat, 0), score * weight(beat))
        if follow == "generator":
            for c in draft:
                add(round(c["beat"], 4), 1.0 + feats.onset_strength(c["beat"] * beat_s))
            if ratio > 1:
                mask = (feats.inst_hits >= b0 * beat_s) & (feats.inst_hits < b1 * beat_s)
                for t, s in zip(feats.inst_hits[mask], feats.inst_hit_strength[mask]):
                    beat = round(t / beat_s / grid) * grid
                    if abs(beat * beat_s - t) <= 0.06:
                        add(round(beat, 4), 0.5 * s / (feats.inst_hit_strength.max() + 1e-9))
        else:
            sources = {"drums": ("kick", "snare"), "kick_snare": ("kick", "snare"), "melody": ("melody",),
                       "vocals": ("vocal",), "mix": ("kick", "snare", "melody", "vocal")}[follow]
            for name in sources:
                times, strength = feats.hits[name]
                mask = (times >= b0 * beat_s - 0.06) & (times < b1 * beat_s)
                for t, s in zip(times[mask], strength[mask]):
                    beat = round(t / beat_s * 4) / 4        # 16th grid for the followed part
                    if abs(beat * beat_s - t) <= 0.06:
                        bonus = 1.2 if follow == "kick_snare" else 1.0
                        add(round(beat, 4), s * bonus)
            if len(pool) < target * 0.6:                    # part too quiet here: lean on the generator
                for c in draft:
                    add(round(c["beat"], 4), 0.4)
        chosen = []
        for beat, _ in sorted(pool.items(), key=lambda kv: -kv[1]):
            if len(chosen) >= max(1, target):
                break
            if all(abs(beat - c) >= spacing for c in chosen):
                chosen.append(beat)
        inside = []
        for beat in sorted(chosen):
            near = min(draft, key=lambda c: abs(c["beat"] - beat), default=None)
            lane = near["key"] if near is not None and abs(near["beat"] - beat) <= 0.25 else 7
            inside.append({"beat": beat, "key": lane, "datamodel": CUBE, "width": 0.25, "volume": 100, "_phrase": id(p)})
        for cube, lane in zip(inside, lane_sequence(p["lanePattern"], inside, feats, beat_s)):
            cube["key"] = lane
        new_cubes += inside
        notes_report.append({"bars": f"{p['startBar']}-{p['endBar']}", "label": p["label"], "follow": follow,
                             "pattern": p["lanePattern"], "density": p["density"], "cars": p["cars"],
                             "doubles": p.get("doubles", "none"), "bonus": p.get("bonus", "none"), "cubes": len(inside)})
    # bars no phrase covered keep the draft as-is
    covered_beats = [(max(0, p["startBar"]) * 4, (max(p["startBar"], p["endBar"]) + 1) * 4) for p in phrases]
    in_plan = lambda beat: any(a <= beat < b for a, b in covered_beats)
    new_cubes += [c for c in cubes if not in_plan(c["beat"])]
    new_cubes.sort(key=lambda c: c["beat"])
    smooth_flow(new_cubes, beat_s)
    new_cubes = add_accents(new_cubes, phrases, feats, beat_s)
    for c in new_cubes:
        c.pop("_phrase", None)
    for p in phrases:
        b0, b1 = max(0, p["startBar"]) * 4, (max(p["startBar"], p["endBar"]) + 1) * 4
        new_cars += make_cars(p["cars"], b0, b1, [c for c in new_cubes if b0 - 2 <= c["beat"] < b1 + 2], beat_s)
    new_cars += [c for c in cars if not in_plan(c["beat"])]
    new_cars = [c for c in new_cars if not car_conflict(c, new_cubes, beat_s)]
    # no two cars in adjacent lanes at (nearly) the same time; never block every lane
    filtered = []
    for car in sorted(new_cars, key=lambda c: c["beat"]):
        close = [c for c in filtered if abs(c["beat"] - car["beat"]) * beat_s < 0.3]
        if any(abs(c["key"] - car["key"]) == 1 for c in close) or len(close) >= 2:
            continue
        filtered.append(car)
    new_cars = filtered

    # events
    events, event_report = [], []
    gameplay_axis = []
    for ev in sorted(plan["events"], key=lambda e: e["beat"]):
        dm = ev["datamodel"]
        if dm not in catalog_by_dm:
            continue
        name = dm.split("/")[-1]
        beat = round(min(max(0.0, float(ev["beat"])), end_beat), 4)
        entity = {"beat": beat, "key": 8, "datamodel": dm}
        axis = 1
        if name == "spawn_ramp":
            flight = min(8.0, max(2.0, round(float(ev["param"] or 4) / 0.125) * 0.125))
            near = min(new_cubes, key=lambda c: abs(c["beat"] - beat), default={"key": 7})
            entity.update(key=near["key"], flightBeats=flight, width=0.25, volume=100)
            new_cubes = [c for c in new_cubes if not (beat - 0.01 <= c["beat"] <= beat + flight)]
            new_cars = [c for c in new_cars if not (beat - 0.5 <= c["beat"] <= beat + flight + 0.5)]
            axis = 0
        elif name == "spawn_wheelie":
            lo, hi = 2 * bpm / 60, 10 * bpm / 60
            entity.update(key=7, wheelieBeats=round(min(hi, max(lo, float(ev["param"] or 4))), 3))
            axis = 0
        elif name == "level_end":
            if any(e["datamodel"].endswith("level_end") for e, _ in events):
                continue
            entity["key"] = 7
        events.append((entity, axis))
        event_report.append({"beat": beat, "event": catalog_by_dm[dm]["label"], "reason": ev["reason"]})
    if not any(e["datamodel"].endswith("level_end") for e, _ in events):
        events.append(({"beat": round(end_beat, 4), "key": 7, "datamodel": "custom_custom_spawn_cube/level_end"}, 1))

    # lyrics styling
    lyrics = [dict(l) for l in chart.get("lyrics") or []]
    for style in plan.get("lyrics", []):
        i = style["index"]
        if 0 <= i < len(lyrics):
            if re.fullmatch(r"#[0-9a-fA-F]{6}", style["color"] or ""):
                lyrics[i]["color"] = style["color"].lower()
            lyrics[i]["position"] = style["position"]
            lyrics[i]["size"] = int(min(120, max(12, style["size"])))
            lyrics[i]["row"] = 2 if style["row"] == 2 else 1

    merged = [(c, 0) for c in new_cubes] + [(c, 0) for c in new_cars] + others + events
    merged.sort(key=lambda pair: (float(pair[0]["beat"]), pair[1]))
    out = json.loads(json.dumps(chart))
    out["entities"] = [e for e, _ in merged]
    out["editorMeta"]["axisMap"] = [ax for _, ax in merged]
    out["musicData"]["trackId"] = plan["scene"]
    if lyrics:
        out["lyrics"] = lyrics
    return out, notes_report, event_report


def land_drops(chart, drops, beat_s):
    """Every drop slams on its first beat: a double (two adjacent lanes) exactly on the downbeat, whatever
    the followed part does there. Cars that would clash with it are removed."""
    axis = chart["editorMeta"]["axisMap"]
    pairs = list(zip(chart["entities"], axis))
    is_cube = lambda entity: kind(entity) in ("spawn_cube", "spawn_jiucai")
    for bar in drops:
        downbeat = bar * 4.0
        on_beat = [e for e, ax in pairs if ax == 0 and is_cube(e) and abs(float(e["beat"]) - downbeat) < 0.01]
        if len(on_beat) >= 2:
            continue
        after = sorted((e for e, ax in pairs if ax == 0 and is_cube(e) and downbeat < float(e["beat"]) <= downbeat + 2),
                       key=lambda e: float(e["beat"]))
        lane = int(on_beat[0]["key"]) if on_beat else int(after[0]["key"]) if after else 7
        lanes = (lane, lane + 1) if lane < 9 else (lane - 1, lane)
        pairs = [(e, ax) for e, ax in pairs if not (e in on_beat)]
        new_cubes = [{"beat": downbeat, "key": key, "datamodel": CUBE, "width": 0.25, "volume": 100} for key in lanes]
        pairs += [(cube, 0) for cube in new_cubes]
        pairs = [(e, ax) for e, ax in pairs
                 if not (ax == 0 and kind(e) == "spawn_sting" and car_conflict(e, new_cubes, beat_s))]
    pairs.sort(key=lambda pair: (float(pair[0]["beat"]), pair[1]))
    chart["entities"] = [e for e, _ in pairs]
    chart["editorMeta"]["axisMap"] = [ax for _, ax in pairs]


# ---------------------------------------------------------------- Claude calls + review pass

def call_claude(client, ledger, system_blocks, user, schema, effort, note, max_out=32000):
    messages = [{"role": "user", "content": user}]
    counted = client.messages.count_tokens(model=MODEL, system=system_blocks, messages=messages).input_tokens
    worst = ledger.check(MODEL, counted + 2000, max_out)
    log(f"{note}: {counted} input tokens, worst-case ${worst:.2f}, budget left ${ledger.remaining:.2f}")
    started = time.time()
    with client.beta.messages.stream(
        model=MODEL, max_tokens=max_out, system=system_blocks, messages=messages,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    ) as stream:
        message = stream.get_final_message()
    cost = ledger.record(message.model, message.usage, note=note)
    log(f"{note} done in {time.time() - started:.0f}s ({message.model}): {message.usage.output_tokens} out tokens, "
        f"${cost:.3f} (total spent ${ledger.data['spent_usd']:.2f})")
    if message.stop_reason == "refusal":
        raise SystemExit(f"Claude declined: {getattr(message, 'stop_details', None)}")
    if message.stop_reason == "max_tokens":
        raise SystemExit("response was cut off (max_tokens); try --effort medium")
    return json.loads(next(b.text for b in message.content if b.type == "text")), cost


def review_schema():
    obj = lambda props: {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}
    return obj({
        "assessment": {"type": "string"},
        "fixes": {"type": "array", "items": obj({
            "startBar": {"type": "integer"}, "endBar": {"type": "integer"}, "label": {"type": "string"},
            "intensity": {"type": "integer"}, "lanePattern": {"type": "string", "enum": LANE_PATTERNS},
            "follow": {"type": "string", "enum": FOLLOW},
            "density": {"type": "string", "enum": list(DENSITIES)}, "cars": {"type": "string", "enum": CAR_PATTERNS},
            "doubles": {"type": "string", "enum": DOUBLES}, "bonus": {"type": "string", "enum": BONUS},
            "reason": {"type": "string"}})},
    })


def review_prompt(plan, directed, rows, grids, metrics, bpm):
    n_bars = len(rows)
    notes = note_grid(directed, bpm, n_bars)
    phrase_of = {}
    for p in plan["phrases"]:
        for bar in range(max(0, p["startBar"]), p["endBar"] + 1):
            phrase_of[bar] = p
    lines = []
    for i in range(n_bars):
        p = phrase_of.get(i, {})
        g = grids[i]
        lines.append(f"{i}|{rows[i]['section'] or '-'}|e{rows[i]['energy']}|{p.get('follow', '?')}/{p.get('lanePattern', '?')}/"
                     f"{p.get('density', '?')}|chart {notes[i]}|K {g['kick']}|S {g['snare']}|M {g['melody']}|V {g['vocal']}")
    return (
        "You planned this chart; here is what the code actually built. Each line: bar|section|energy|follow/pattern/"
        "density|chart (16 steps: lane digit = cube in that lane, D = double, b = bonus cube, c = car only, . = empty)"
        "|kick|snare|melody|vocal (X strong, x hit).\n\n" + "\n".join(lines) +
        f"\n\nFlow metrics: {json.dumps(metrics)}\n\n"
        "Play it in your head against the music. Find the weak spots: notes off the part the player hears most, "
        "rhythms that ignore an obvious kick/snare/vocal hook, sections too crowded or too empty FOR THEIR ENERGY "
        "(rests where the music is quiet are good - do not fill them), "
        "patterns that repeat when the music changes (or change when it repeats), too many or misplaced doubles. "
        "Return replacement settings only for bar ranges that should change (often 3-10 fixes; none if it is good). "
        "Keep doubles rare."
    )


def merge_fixes(plan, fixes):
    """Fixes override the plan bar by bar; consecutive bars with the same settings become one phrase."""
    n = max([p["endBar"] for p in plan["phrases"]] + [f["endBar"] for f in fixes] + [0]) + 1
    per_bar = [None] * n
    for p in plan["phrases"]:
        for bar in range(max(0, p["startBar"]), min(n, p["endBar"] + 1)):
            per_bar[bar] = p
    for f in fixes:
        for bar in range(max(0, f["startBar"]), min(n, f["endBar"] + 1)):
            per_bar[bar] = f
    phrases, start = [], 0
    for bar in range(1, n + 1):
        if bar == n or per_bar[bar] is not per_bar[start]:
            if per_bar[start] is not None:
                phrases.append({**per_bar[start], "startBar": start, "endBar": bar - 1})
            start = bar
    return {**plan, "phrases": phrases}


# ---------------------------------------------------------------- flow checker

def flow_metrics(chart, rows, beat_s):
    cubes, cars, _ = split_chart(chart)
    cubes.sort(key=lambda c: c["beat"])
    moves = [abs(b["key"] - a["key"]) for a, b in zip(cubes, cubes[1:])]
    fast_big = sum(1 for a, b in zip(cubes, cubes[1:]) if (b["beat"] - a["beat"]) * beat_s < 0.25 and abs(b["key"] - a["key"]) > 2)
    per_bar = np.zeros(len(rows))
    for c in cubes:
        bar = int(c["beat"] // 4)
        if bar < len(per_bar):
            per_bar[bar] += 1
    energy = np.array([r["energy"] for r in rows], dtype=float)
    corr = float(np.corrcoef(per_bar, energy)[0, 1]) if per_bar.std() > 0 and energy.std() > 0 else 0.0
    lanes = np.bincount([c["key"] - 5 for c in cubes], minlength=5) / max(1, len(cubes))
    beats = [round(c["beat"], 3) for c in cubes]
    doubles = sum(1 for b in set(beats) if beats.count(b) > 1)
    return {
        "cubes": len(cubes), "cars": len(cars), "doubles": doubles,
        "bonus_cubes": sum(1 for c in cubes if kind(c) == "spawn_jiucai"),
        "avg_lane_move": round(float(np.mean(moves)), 2) if moves else 0,
        "impossible_fast_jumps": fast_big,
        "car_conflicts": sum(1 for car in cars if car_conflict(car, cubes, beat_s)),
        "density_follows_energy": round(corr, 2),
        "lane_use_pct": [int(x * 100) for x in lanes],
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chart_dir", help="folder made by make_chart.py (chart.json + report.json)")
    ap.add_argument("--difficulty", type=int, default=2, choices=range(5))
    ap.add_argument("--scene", choices=SCENES, help="force a scene (default: Claude chooses)")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--budget", type=float, default=30.0, help="total USD limit across all runs")
    ap.add_argument("--dry-run", action="store_true", help="count tokens and show worst-case cost; no generation")
    ap.add_argument("--plan", help="reuse a saved plan.json instead of calling Claude")
    ap.add_argument("--no-review", action="store_true", help="skip the second (review) pass")
    ap.add_argument("--no-align-audio", action="store_true", help="don't pad the audio to put the first downbeat on a whole beat")
    ap.add_argument("--keep-tempo", action="store_true", help="trust the generator's BPM instead of fitting it to the drums")
    args = ap.parse_args()

    load_env()
    chart_dir = os.path.abspath(args.chart_dir)
    with open(os.path.join(chart_dir, "chart.json"), encoding="utf-8") as fh:
        chart = json.load(fh)
    with open(os.path.join(chart_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    stems_dir = os.path.dirname(report["files"]["vocals"])
    # the event types come from the chart editor in your game install (nothing of the game's is shipped)
    import catalog_from_game
    catalog = catalog_from_game.load_catalog()
    catalog_by_dm = {t["datamodel"]: t for t in catalog}

    feats = Features(stems_dir)
    nominal_bpm = float(chart["musicData"]["bpm"])
    if args.keep_tempo:
        bpm, offset_s, consistency = nominal_bpm, 0.0, None
    else:
        bpm, offset_s, consistency = fit_tempo(feats, nominal_bpm)
        log(f"tempo: generator said {nominal_bpm:g} BPM; the drums say {bpm:g} BPM with the first downbeat at "
            f"{offset_s * 1000:.0f} ms (kick consistency {consistency})")
    retime_chart(chart, bpm, offset_s)
    shift_features(feats, offset_s)
    beat_s = 60.0 / bpm
    # Pad the audio so the first downbeat sits on a whole beat: then notes, the game's own beat clock and the
    # music agree with musicData.offset = 0, whatever the game does with that field.
    audio_pad_s, written_offset_s = 0.0, offset_s
    if offset_s and not args.no_align_audio:
        audio_pad_s = round((beat_s - offset_s % beat_s) % beat_s, 4)
        written_offset_s = offset_s + audio_pad_s
        source_audio = next(os.path.join(chart_dir, name) for name in ("audio.mp3", "audio.ogg", "audio.wav")
                            if os.path.exists(os.path.join(chart_dir, name)))
        write_aligned_audio(source_audio, os.path.join(chart_dir, "audio_aligned.ogg"), audio_pad_s)
        log(f"audio_aligned.ogg: {audio_pad_s * 1000:.0f} ms of silence added, so the first downbeat is beat "
            f"{round(written_offset_s / beat_s)} exactly")
    total_beats = len(feats.inst_rms) * feats.hop / beat_s
    rows = bar_table(chart, feats, bpm, total_beats)
    drops = find_drops(rows, feats, bpm)
    for bar in drops:
        rows[bar]["drop"] = True
    log(f"drops at bars {drops} ({', '.join(f'{(bar * 4 * beat_s + offset_s):.1f}s' for bar in drops)})")
    lyrics_lines = [{"time": l["beat"] * beat_s, "beat": l["beat"], "text": l["text"]} for l in chart.get("lyrics") or []]
    style = build_profile(WORKSHOP_DIR) if os.path.isdir(WORKSHOP_DIR) else None
    grids = rhythm_grid(feats, bpm, len(rows))
    system, user, allowed = build_prompt(chart, rows, lyrics_lines, args.scene, args.difficulty, style, catalog, grids)
    schema = plan_schema(allowed, len(lyrics_lines), args.scene)
    system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    cost, review_note = 0.0, None

    if args.plan:
        with open(args.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
    else:
        import anthropic
        client = anthropic.Anthropic()
        ledger = Ledger(os.path.join(HERE, "spend_ledger.json"), args.budget)
        if args.dry_run:
            counted = client.messages.count_tokens(model=MODEL, system=system_blocks,
                                                   messages=[{"role": "user", "content": user}]).input_tokens
            log(f"dry run: {counted} input tokens for the plan; review pass adds a similar request. "
                f"Budget left ${ledger.remaining:.2f} of ${args.budget:.2f}")
            print(user[:2500])
            return
        plan, c1 = call_claude(client, ledger, system_blocks, user, schema, args.effort, f"plan {os.path.basename(chart_dir)}")
        cost += c1
        with open(os.path.join(chart_dir, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=1, ensure_ascii=False)
        if not args.no_review:
            draft, _, _ = apply_plan(chart, plan, feats, args.difficulty, catalog_by_dm)
            review_user = review_prompt(plan, draft, rows, grids, flow_metrics(draft, rows, beat_s), bpm)
            review, c2 = call_claude(client, ledger, system_blocks, review_user, review_schema(), args.effort,
                                     f"review {os.path.basename(chart_dir)}")
            cost += c2
            review_note = {"assessment": review["assessment"], "fixes": len(review["fixes"])}
            plan = merge_fixes(plan, review["fixes"])
            with open(os.path.join(chart_dir, "plan_reviewed.json"), "w", encoding="utf-8") as fh:
                json.dump({**plan, "review": review}, fh, indent=1, ensure_ascii=False)

    directed, notes_report, event_report = apply_plan(chart, plan, feats, args.difficulty, catalog_by_dm)
    land_drops(directed, drops, beat_s)
    before, after = flow_metrics(chart, rows, beat_s), flow_metrics(directed, rows, beat_s)
    to_absolute_beats(directed, written_offset_s)
    if audio_pad_s:
        directed["musicData"].update({"filename": "audio_aligned", "extension": "ogg"})
    out_path = os.path.join(chart_dir, "chart_directed.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(directed, fh, ensure_ascii=False)
    follows = {}
    for r in notes_report:
        follows[r["follow"]] = follows.get(r["follow"], 0) + 1
    summary = {"scene": plan["scene"], "summary": plan["summary"], "cost_usd": round(cost, 3), "review": review_note,
               "flow_before": before, "flow_after": after, "phrase_follow_counts": follows,
               "tempo": {"generator_bpm": nominal_bpm, "bpm": bpm, "offset_s": offset_s, "consistency": consistency,
                         "audio_pad_s": audio_pad_s, "audio": "audio_aligned.ogg" if audio_pad_s else "original"},
               "drops": [{"bar": bar, "time_s": round(bar * 4 * beat_s + written_offset_s, 2)} for bar in drops],
               "phrases": notes_report, "events": event_report,
               "lyric_lines_styled": len(plan.get("lyrics", [])), "chart": out_path}
    with open(os.path.join(chart_dir, "director_report.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: summary[k] for k in ("scene", "cost_usd", "review", "flow_before", "flow_after",
                                              "phrase_follow_counts", "tempo", "drops", "lyric_lines_styled", "chart")}, indent=1, ensure_ascii=True))
    print(f"phrases: {len(notes_report)}, events: {len(event_report)}")


if __name__ == "__main__":
    main()
