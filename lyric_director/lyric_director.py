"""Claude lyric director: cleans up a chart's lyrics and designs its 3D lyric signs.

  1. Word timings from the vocal stem (faster-whisper large-v3 + wav2vec2 alignment, cached in
     <chart folder>/lyrics_words.json). With --lyrics-text, your own copy of the lyrics is aligned instead.
  2. Claude (same API key and $30 spending cap as the AI director) gets the words with their times and
     the song's energy per bar, and returns:
       - corrected words (mis-hearings fixed, hallucinated credits dropped),
       - phrases split where a singer would breathe / a lyric video would cut,
       - a sign design per phrase: line breaks, emphasis, colour, side, font, and which
         reveal / enter / exit animation fits that moment (soft verse vs. chorus hit vs. drop).
  3. Writes a new chart with the cleaned normal lyrics and the "lyric3d" design.

Claude only edits what Whisper heard - it never adds lyrics from memory. For exact words, paste
lyrics you have into a text file and pass --lyrics-text.

  python lyric_director.py "<chart folder>/chart_directed.json" \
      --vocals ".../vocals.wav" --audio ".../audio.mp3" --out ".../We Found Love (Claude Lyrics).json"
"""
import argparse
import json
import os
import re
import sys

import numpy as np

# keep model downloads on D: with the rest of the pipeline (C: is nearly full)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ai_director"))
sys.path.insert(0, os.path.join(ROOT, "chart_pipeline"))

import director                                  # noqa: E402  (call_claude, frames, load_env, MODEL)
import paths                                     # noqa: E402

paths.use_work_dir_for_model_caches()
from budget import Ledger                        # noqa: E402

FONTS = ["default", "Impact", "Arial Black", "Bahnschrift", "Segoe UI Black", "Georgia", "Consolas"]
EMPHASIS_SIZE = {"small": 0.7, "normal": 1.0, "big": 1.35, "huge": 1.7}
SIGN_SCALE = {"small": 0.8, "normal": 1.0, "large": 1.25, "huge": 1.6}
SIGN_HEIGHT = {"low": 4.5, "normal": 7.0, "high": 11.0}
REVEALS = ["karaoke", "typewriter", "none"]
ENTERS = ["rise", "fade", "pop", "drop"]
EXITS = ["fade", "dissolve", "shrink", "rise"]
MOMENTS = ["intro", "verse", "prechorus", "chorus", "hook", "drop", "bridge", "breakdown", "outro", "adlib"]


def log(message):
    print(f"[lyric director] {message}", flush=True)


# ---------------------------------------------------------------- inputs

def load_words(chart_dir, vocals_path, lyrics_text_path):
    cache = os.path.join(chart_dir, "lyrics_words.json")
    if os.path.exists(cache) and not lyrics_text_path:
        log(f"using cached word timings: {cache}")
        return json.load(open(cache, encoding="utf-8"))
    import lyrics_whisper
    audio = lyrics_whisper.load_16k(vocals_path)
    if lyrics_text_path:
        heard = lyrics_whisper.transcribe(audio, "en", log=log)
        official = lyrics_whisper.words_from_text(open(lyrics_text_path, encoding="utf-8").read())
        if heard:
            positions = np.linspace(0, len(heard) - 1, num=len(official)).round().astype(int)
            for word, index in zip(official, positions):
                word["start"], word["end"] = heard[index]["start"], heard[index]["end"]
        words = lyrics_whisper.force_align(audio, official, log=log)
    else:
        words = lyrics_whisper.force_align(audio, lyrics_whisper.transcribe(audio, "en", log=log), log=log)
    words = [{"start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3), "text": w["text"],
              "prob": round(float(w.get("prob", 1.0)), 2)} for w in words if "start" in w]
    json.dump(words, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"saved {len(words)} word timings to {cache}")
    return words


def energy_per_bar(audio_path, bpm, total_seconds):
    """0-9 loudness per 4-beat bar of the full mix."""
    _, rms, _, hop_s = director.frames(audio_path, hop_s=0.05)
    bar_seconds = 4 * 60.0 / bpm
    bars = []
    for bar in range(int(total_seconds / bar_seconds) + 1):
        start, end = int(bar * bar_seconds / hop_s), int((bar + 1) * bar_seconds / hop_s)
        bars.append(float(rms[start:end].mean()) if end <= len(rms) and end > start else 0.0)
    values = np.log(np.array(bars) + 1e-4)
    low, high = np.percentile(values, 5), np.percentile(values, 98)
    return [int(np.clip((value - low) / max(1e-6, high - low) * 9, 0, 9)) for value in values], bar_seconds


# ---------------------------------------------------------------- prompt

GUIDE = """You are the lyric-video director for "Beat For Speed", a rhythm driving game. While the player drives,
each lyric phrase appears as a big 3D sign standing beside the road ahead (a 2D text panel in the 3D world).
The sign comes into view several seconds early, the words light up as they are sung, and the player drives
past it shortly after the phrase ends. Think of title cards in a great lyric music video, placed in the world.

You get the words a speech recogniser heard on the isolated vocal track (index, start/end seconds, confidence)
and the song's loudness per bar. Your job:

1. CLEAN UP. Fix obvious mis-hearings and spelling using the context of the surrounding words (e.g. a
   misheard word that breaks the sentence). Keep exactly what is sung: never add lines or words that have no
   matching recognised word, never rewrite meaning. Drop words that are not lyrics: recogniser hallucinations
   such as subtitle credits, "thank you for watching", copyright notices, or garbage over instrumental parts
   (list their indices in dropped_word_indices). Repeated hooks are real lyrics - keep them.

2. PHRASES. Group consecutive words into phrases, one sign each: split where the singer breathes or the line
   ends (look at the gaps between word times), 2-8 words usually, never longer than ~4.5 seconds unless a
   word is held. A short punchy hook can be its own sign. Every kept word must be in exactly one phrase,
   phrases in time order, no overlaps.

3. DESIGN each sign so the animation hits the right moment:
   - lines: 1-3 display lines; break like a title card (e.g. small lead-in line + big key words).
     Text in UPPERCASE for the bold title-card look; use sentence case only for soft/intimate moments.
     The words across the lines must be the phrase's words in order (with your corrections).
   - emphasis per line: small / normal / big / huge. Put the size on the meaningful words, use huge rarely.
   - colour per line (#rrggbb, readable on a dark city/forest/coast background). Keep a palette per section
     (e.g. cool blues/whites for verses, hot pinks/golds for the chorus) and change it when the section changes.
   - moment: what part of the song this is.
   - reveal: karaoke (words light up as sung - best for sung lines), typewriter (letters appear - fast,
     rhythmic or spoken lines), none (whole text at once - one-word shouts, hooks you want to slam in).
   - enter: SUBTLE BY DEFAULT - the player is driving, and lots of motion reads as distracting bouncing.
     fade for verses, intros, breakdowns and outros; rise (a gentle lift) for pre-choruses and choruses;
     pop or drop ONLY on the few biggest hits (the drops, the first line of the last chorus) - at most ~4 signs. exit: fade (default), dissolve (end of a section, dreamy),
     shrink (quick lines), rise (uplifting, lifts away).
   - pulse: true only for choruses and drops (the sign throbs on each beat), false everywhere else.
   - scale: small / normal / large / huge - the whole sign. Bigger for choruses and drops, smaller for ad-libs.
   - height: low / normal / high above the road. Vary it a little for interest; high for the biggest moments.
   - side: left / right of the road. Alternate when phrases come close together (< ~3 s apart) so signs don't
     stack on each other; repeated hook lines can ping-pong.
   - font: "default" (the game's font) or one of the listed fonts. Pick one main font for the song and switch only
     for special moments (e.g. the drop).
   - gradient_bottom: "" for a flat colour, or a second #rrggbb to fade the text into at the bottom (use for
     choruses/drops, not everything).
   Contrast matters: build up through the song, keep the biggest effects (drop enter, huge, pulse, gradient)
   for the moments that deserve them, so they land. Calm parts should feel calm.

Also return "notes": 2-4 sentences on your overall concept."""


def chart_story(chart_dir):
    """The AI director's summary of the chart (scene, theme changes, drops), so the signs match the visuals."""
    path = os.path.join(chart_dir, "director_report.json")
    if not os.path.exists(path):
        return ""
    report = json.load(open(path, encoding="utf-8"))
    story = ("\n\nThe chart's visual story (match your sign colours and big moments to it):\n"
             + report.get("summary", ""))
    drops = report.get("drops") or []
    if drops:
        story += ("\n\nTHE DROPS (measured from the drums) hit at " + ", ".join(f"{drop['time_s']:.1f} s" for drop in drops)
                  + ". These are the song's biggest moments: the first sign sung at or right after each drop is your"
                  " showpiece (pop or drop entrance, huge or large, high, gradient, pulse, a bold drop font), and the"
                  " last sign before it should build anticipation. Keep everything else calm so the drops stand out.")
    return story


def build_request(chart, words, energies, bar_seconds, story=""):
    bpm = float(chart["musicData"]["bpm"])
    word_rows = "\n".join(f"{index}\t{word['start']:.2f}\t{word['end']:.2f}\t{word.get('prob', 1):.2f}\t{word['text']}"
                          for index, word in enumerate(words))
    energy_text = " ".join(str(value) for value in energies)
    title = re.sub(r"\s*\(\d+\)$", "", (chart.get("bfsMetadata") or {}).get("songName") or "unknown")
    return (f"Song: {title}; tempo {bpm:g} BPM; "
            f"one bar = {bar_seconds:.2f} s.\n\nLoudness per bar (0 quiet - 9 loudest), bar 0 starts at 0 s:\n"
            f"{energy_text}\n\nRecognised words (index, start s, end s, confidence, text):\n{word_rows}\n\n"
            f"Fonts you may use: {', '.join(FONTS)}.{story}")


def schema(word_count):
    line = {"type": "object", "additionalProperties": False, "required": ["text", "emphasis", "color"],
            "properties": {"text": {"type": "string"}, "emphasis": {"type": "string", "enum": list(EMPHASIS_SIZE)},
                           "color": {"type": "string"}}}
    phrase = {"type": "object", "additionalProperties": False,
              "required": ["first_word", "last_word", "plain_text", "lines", "moment", "reveal", "enter", "exit",
                           "pulse", "scale", "height", "side", "font", "gradient_bottom"],
              "properties": {
                  "first_word": {"type": "integer"}, "last_word": {"type": "integer"},
                  "plain_text": {"type": "string", "description": "the phrase in normal sentence case for the flat on-screen lyrics"},
                  "lines": {"type": "array", "items": line},
                  "moment": {"type": "string", "enum": MOMENTS},
                  "reveal": {"type": "string", "enum": REVEALS},
                  "enter": {"type": "string", "enum": ENTERS},
                  "exit": {"type": "string", "enum": EXITS},
                  "pulse": {"type": "boolean"},
                  "scale": {"type": "string", "enum": list(SIGN_SCALE)},
                  "height": {"type": "string", "enum": list(SIGN_HEIGHT)},
                  "side": {"type": "string", "enum": ["left", "right"]},
                  "font": {"type": "string", "enum": FONTS},
                  "gradient_bottom": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["notes", "dropped_word_indices", "phrases"],
            "properties": {"notes": {"type": "string"},
                           "dropped_word_indices": {"type": "array", "items": {"type": "integer"}},
                           "phrases": {"type": "array", "items": phrase}}}


# ---------------------------------------------------------------- apply

def valid_color(value, fallback="#ffffff"):
    value = (value or "").strip()
    return value.lower() if len(value) == 7 and value.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in value[1:]) else fallback


def apply_design(chart, words, design):
    bpm = float(chart["musicData"]["bpm"])
    beats_per_second = bpm / 60.0
    dropped = set(design.get("dropped_word_indices", []))
    phrases = sorted(design.get("phrases", []), key=lambda phrase: phrase["first_word"])
    last_used = -1
    lyrics, panels, problems = [], [], []
    for phrase in phrases:
        first = max(int(phrase["first_word"]), last_used + 1)
        last = min(int(phrase["last_word"]), len(words) - 1)
        if last < first:
            problems.append(f"skipped overlapping/empty phrase {phrase['first_word']}-{phrase['last_word']}")
            continue
        last_used = last
        start, end = words[first]["start"], max(words[last]["end"], words[first]["start"] + 0.3)
        lines = [{"text": line["text"].strip(), "size": EMPHASIS_SIZE.get(line["emphasis"], 1.0),
                  "color": valid_color(line["color"]), "bold": True, "italic": False}
                 for line in phrase["lines"] if line["text"].strip()][:3]
        if not lines:
            continue
        beat, duration = round(start * beats_per_second, 4), round((end - start) * beats_per_second, 4)
        lyrics.append({"beat": beat, "duration": duration, "text": phrase["plain_text"].strip() or " ".join(l["text"] for l in lines),
                       "row": 1, "color": lines[0]["color"], "syncConfidence": "high"})
        panel = {"beat": beat, "duration": duration, "lines": lines,
                 "side": -1 if phrase["side"] == "left" else 1, "distance": 15, "height": SIGN_HEIGHT[phrase["height"]],
                 "turn": 60, "scale": SIGN_SCALE[phrase["scale"]], "opacity": 0.95, "outline": 0.15, "spacing": 4,
                 "reveal": phrase["reveal"], "enter": phrase["enter"], "exit": phrase["exit"], "pulse": bool(phrase["pulse"])}
        if phrase["font"] != "default":
            panel["font"] = phrase["font"]
        bottom = valid_color(phrase.get("gradient_bottom"), "")
        if bottom:
            panel["gradient"] = [lines[0]["color"], bottom]
        panels.append(panel)
    covered = {index for phrase in phrases for index in range(phrase["first_word"], phrase["last_word"] + 1)}
    missing = [index for index in range(len(words)) if index not in covered and index not in dropped]
    if missing:
        problems.append(f"{len(missing)} words neither used nor dropped (first: {missing[:8]})")
    chart["lyrics"] = lyrics
    chart["lyric3d"] = {"version": 1, "panels": panels}
    chart.pop("lyricFxSource", None)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chart")
    parser.add_argument("--vocals", required=True, help="isolated vocal stem (from make_chart.py)")
    parser.add_argument("--audio", required=True, help="full mix, for the song's energy")
    parser.add_argument("--out", required=True)
    parser.add_argument("--lyrics-text", help="optional text file with the lyrics (aligned instead of recognised)")
    parser.add_argument("--effort", default="xhigh", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--budget", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true", help="show the request and token count, no API call")
    args = parser.parse_args()

    director.load_env()
    chart = json.load(open(args.chart, encoding="utf-8"))
    words = load_words(os.path.dirname(os.path.abspath(args.out)), args.vocals, args.lyrics_text)
    bpm = float(chart["musicData"]["bpm"])
    energies, bar_seconds = energy_per_bar(args.audio, bpm, words[-1]["end"] + 10 if words else 240)
    request = build_request(chart, words, energies, bar_seconds, chart_story(os.path.dirname(os.path.abspath(args.chart))))
    system_blocks = [{"type": "text", "text": GUIDE, "cache_control": {"type": "ephemeral"}}]
    log(f"{len(words)} words, {len(energies)} bars")
    if args.dry_run:
        print(request[:3000])
        return

    import anthropic
    client = anthropic.Anthropic()
    ledger = Ledger(os.path.join(ROOT, "ai_director", "spend_ledger.json"), args.budget)
    design, cost = director.call_claude(client, ledger, system_blocks, request, schema(len(words)), args.effort,
                                        "lyric director", max_out=24000)
    problems = apply_design(chart, words, design)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    json.dump(design, open(os.path.join(out_dir, "lyric_design.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(chart, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"concept: {design.get('notes', '')}")
    for problem in problems:
        log(f"warning: {problem}")
    moments = {}
    for phrase in design["phrases"]:
        moments[phrase["moment"]] = moments.get(phrase["moment"], 0) + 1
    log(f"{len(chart['lyric3d']['panels'])} signs, dropped {len(design.get('dropped_word_indices', []))} words, "
        f"moments {moments}; cost ${cost:.3f}; wrote {args.out}")


if __name__ == "__main__":
    main()
