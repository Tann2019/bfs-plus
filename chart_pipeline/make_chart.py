"""Vocal-free chart generation for Beat For Speed.

The game's chart_generator places notes on whatever is loudest/most percussive, which
often means the singer. This pipeline:

  1. splits the song with Demucs (htdemucs, two stems: vocals / no_vocals),
  2. runs the game's own chart_generator on the instrumental only,
  3. (default) also runs it on the full mix, and keeps that run's song-structure markers,
     because the generator's section detection uses vocal cues ("voice 0.98"),
  4. writes one chart that plays the ORIGINAL song, plus a report comparing how many
     notes land on vocals with and without separation.

Run with the Demucs venv's python (it has torch/numpy/soundfile):
  python make_chart.py "song.mp3" -d 2 --scene city
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

paths.use_work_dir_for_model_caches()
GAME_DIR = paths.game_dir()
GENERATOR = os.path.join(GAME_DIR, r"Tools\chart_generator\chart_generator\chart_generator.exe")
FFMPEG_BIN = os.path.join(GAME_DIR, r"Tools\ffmpeg\bin")
CACHE_DIR = os.environ.get("BFS_STEM_CACHE", os.path.join(paths.work_dir(), "stems"))
# ffmpeg: the one on PATH, else the copy the game ships with
if not shutil.which("ffmpeg") and os.path.isdir(FFMPEG_BIN):
    os.environ["PATH"] = FFMPEG_BIN + os.pathsep + os.environ.get("PATH", "")
NOTE_TYPES = ("spawn_cube", "spawn_sting", "spawn_jiucai", "spawn_ramp")
STRUCTURE_PREFIX = "custom_song_structure"
ANALYSIS_RATE = 11025


def write_ogg(source, destination):
    """Copy an .ogg as-is; convert anything else with ffmpeg (Vorbis, quality 6)."""
    if source.lower().endswith(".ogg"):
        shutil.copyfile(source, destination)
        return
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
                    "-c:a", "libvorbis", "-q:a", "6", destination], check=True)


def log(msg):
    print(f"[make_chart] {msg}", flush=True)


def file_key(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def decode_to_wav(audio, wav_path, rate=44100):
    """Decode any input (mp3/ogg/flac/...) to stereo float WAV with the game's bundled ffmpeg."""
    subprocess.run([os.path.join(FFMPEG_BIN, "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-y", "-i", audio,
                    "-ac", "2", "-ar", str(rate), "-c:a", "pcm_f32le", wav_path], check=True)


def separate_torchaudio(audio, out_dir, device):
    """Hybrid Demucs (v3, MUSDB-HQ + extra data) via torchaudio; weights come from download.pytorch.org."""
    import torch
    import torchaudio
    from torchaudio.transforms import Fade

    bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
    rate = bundle.sample_rate
    tmp_wav = os.path.join(out_dir, "_input.wav")
    decode_to_wav(audio, tmp_wav, rate)
    data, _ = sf.read(tmp_wav, dtype="float32", always_2d=True)
    os.remove(tmp_wav)
    device = device if (device != "cuda" or torch.cuda.is_available()) else "cpu"
    model = bundle.get_model().to(device).eval()
    mix = torch.from_numpy(data.T.copy()).to(device)            # (channels, samples)
    ref = mix.mean(0)
    mean, std = ref.mean(), ref.std()
    mix = ((mix - mean) / std).unsqueeze(0)                     # (1, channels, samples)

    # Chunked inference with linear cross-fades (the approach from torchaudio's HDemucs tutorial).
    segment, overlap = 10.0, 0.1
    length = mix.shape[-1]
    chunk = int(rate * segment * (1 + overlap))
    overlap_frames = int(overlap * rate)
    fade = Fade(fade_in_len=0, fade_out_len=overlap_frames, fade_shape="linear")
    out = torch.zeros(1, len(model.sources), mix.shape[1], length, device=device)
    start, end = 0, chunk
    with torch.no_grad():
        while start < length - overlap_frames:
            part = fade(model(mix[:, :, start:end]))
            out[:, :, :, start:start + part.shape[-1]] += part
            if start == 0:
                fade.fade_in_len = overlap_frames
                start += chunk - overlap_frames
            else:
                start += chunk
            end += chunk
            if end >= length:
                fade.fade_out_len = 0
    out = (out * std + mean)[0]                                 # (sources, channels, samples)
    stems = dict(zip(model.sources, out))
    vocals = stems["vocals"]
    no_vocals = sum(stem for name, stem in stems.items() if name != "vocals")
    outputs = [("vocals.wav", vocals), ("no_vocals.wav", no_vocals)] + [(f"{name}.wav", stems[name]) for name in ("drums", "bass", "other")]
    for name, tensor in outputs:
        sf.write(os.path.join(out_dir, name), tensor.T.clamp(-1, 1).cpu().numpy(), rate, subtype="PCM_16")


def separate(audio, device, model):
    """Return (vocals.wav, no_vocals.wav), cached by file content hash."""
    out_dir = os.path.join(CACHE_DIR, f"{file_key(audio)}_{model}")
    vocals, inst = os.path.join(out_dir, "vocals.wav"), os.path.join(out_dir, "no_vocals.wav")
    needed = [vocals, inst] + ([os.path.join(out_dir, f"{n}.wav") for n in ("drums", "bass", "other")] if model == "hdemucs" else [])
    if all(os.path.exists(p) for p in needed):
        log(f"stems cached: {out_dir}")
        return vocals, inst
    os.makedirs(out_dir, exist_ok=True)
    if model == "hdemucs":
        log(f"separating vocals with Hybrid Demucs (torchaudio, {device})...")
        started = time.time()
        separate_torchaudio(audio, out_dir, device)
        log(f"separation done in {time.time() - started:.0f}s")
        return vocals, inst
    env = dict(os.environ, PATH=FFMPEG_BIN + os.pathsep + os.environ.get("PATH", ""),
               TORCH_HOME=os.environ.get("TORCH_HOME", os.path.join(os.path.dirname(CACHE_DIR), "torch")))
    cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", model, "-d", device,
           "-o", out_dir, "--filename", "{stem}.{ext}", audio]
    log(f"separating vocals with Demucs ({model}, {device})...")
    started = time.time()
    subprocess.run(cmd, check=True, env=env)
    produced = os.path.join(out_dir, model)
    for name in ("vocals.wav", "no_vocals.wav"):
        shutil.move(os.path.join(produced, name), os.path.join(out_dir, name))
    shutil.rmtree(produced, ignore_errors=True)
    log(f"separation done in {time.time() - started:.0f}s")
    return vocals, inst


def run_generator(audio, out_json, args):
    cmd = [GENERATOR, audio, "-d", str(args.difficulty), "-p", args.pattern, "--density", str(args.density),
           "-t", str(args.threshold), "--no-ogg", "-o", out_json]
    log(f"chart_generator on {os.path.basename(audio)}...")
    result = subprocess.run(cmd, cwd=os.path.dirname(GENERATOR), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0 or not os.path.exists(out_json):
        sys.stderr.write(result.stdout[-3000:] + result.stderr[-3000:])
        raise RuntimeError(f"chart_generator failed ({result.returncode})")
    with open(out_json, encoding="utf-8") as fh:
        return json.load(fh)


def is_note(entity):
    return entity.get("datamodel", "").split("/")[-1] in NOTE_TYPES


def is_structure(entity):
    return entity.get("datamodel", "").startswith(STRUCTURE_PREFIX)


def merge(inst_chart, full_chart, original_audio, scene):
    """Notes from the instrumental run, structure markers (and their types) from the full-mix run."""
    bpm = float(inst_chart["musicData"]["bpm"])
    inst_axis = (inst_chart.get("editorMeta") or {}).get("axisMap") or [0] * len(inst_chart["entities"])
    entities, axis = [], []
    for entity, ax in zip(inst_chart["entities"], inst_axis):
        if full_chart is not None and is_structure(entity):
            continue  # replaced by the full-mix structure below
        entities.append(entity)
        axis.append(ax)
    meta = dict(inst_chart.get("editorMeta") or {})
    if full_chart is not None:
        full_bpm = float(full_chart["musicData"]["bpm"])
        # Both runs use the same -2 s JSON offset convention, so beats convert by the BPM ratio.
        ratio = bpm / full_bpm
        for entity in full_chart["entities"]:
            if is_structure(entity):
                entities.append({**entity, "beat": round(float(entity["beat"]) * ratio, 4)})
                axis.append(1)
        full_meta = full_chart.get("editorMeta") or {}
        for key in ("datamodelTypes", "typeGroups", "songStructure"):
            if key in full_meta:
                meta[key] = full_meta[key]
    order = sorted(range(len(entities)), key=lambda i: (float(entities[i]["beat"]), axis[i]))
    meta["axisMap"] = [axis[i] for i in order]
    base, ext = os.path.splitext(os.path.basename(original_audio))
    music = dict(inst_chart["musicData"])
    # charts ship with OGG audio: the editor warns (with a blocking dialog) about MP3 timing on import
    music.update({"filename": "audio", "extension": "ogg"})
    if scene:
        music["trackId"] = scene
    return {"musicData": music, "entities": [entities[i] for i in order], "editorMeta": meta}


# ---------- gap filler ----------

def strong_onsets(signal_path, percentile=80):
    """Times (s) and strengths of clear instrumental hits, at least 100 ms apart."""
    _, flux = onset_envelope(load_mono(signal_path))
    threshold = np.percentile(flux, percentile)
    peaks = [i for i in range(1, len(flux) - 1) if flux[i] > threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    kept = []
    for p in peaks:
        if kept and p - kept[-1] < 10:
            if flux[p] > flux[kept[-1]]:
                kept[-1] = p
            continue
        kept.append(p)
    return np.array(kept) * 0.01, flux[kept] if kept else np.array([])


def fill_gaps(chart, inst_path, difficulty, min_gap_beats=4.0, min_hits=6):
    """The generator sometimes leaves long holes during busy music (e.g. a whole build-up before a
    drop). Fill holes of `min_gap_beats`+ that contain `min_hits`+ strong instrumental hits with
    cubes on those hits, snapped to the beat grid, at the density of the surrounding music."""
    bpm = float(chart["musicData"]["bpm"])
    beat_s = 60.0 / bpm
    grid = 0.5 if difficulty <= 2 else 0.25            # beats
    spacing = 0.5 if difficulty <= 2 else 0.25         # minimum beats between added notes
    hit_times, hit_strength = strong_onsets(inst_path)
    hit_beats = hit_times / beat_s
    axis = chart["editorMeta"]["axisMap"]
    notes = sorted((float(e["beat"]), int(e.get("key", 7))) for e, ax in zip(chart["entities"], axis) if ax == 0 and is_note(e))
    beats = np.array([b for b, _ in notes])
    added = []
    for (a, lane_a), (b, _) in zip(notes[:-1], notes[1:]):
        if b - a < min_gap_beats:
            continue
        inside = (hit_beats > a + 0.5) & (hit_beats < b - 0.5)
        if inside.sum() < min_hits:
            continue
        around = ((beats >= a - 16) & (beats <= a)).sum() + ((beats >= b) & (beats <= b + 16)).sum()
        density = max(0.5, around / 32.0)              # notes per beat in the 16 beats on each side
        want = int(round(density * (b - a - 1)))
        candidates = []
        for t, s in zip(hit_beats[inside], hit_strength[inside]):
            snapped = round(t / grid) * grid
            if abs(snapped - t) * beat_s <= 0.06:      # only hits that sit on the grid
                candidates.append((s * (1.5 if snapped % 1 == 0 else 1.0), snapped))  # prefer on-beat hits
        chosen = []
        for _, beat in sorted(candidates, reverse=True):
            if len(chosen) >= want:
                break
            if all(abs(beat - c) >= spacing for c in chosen) and beat - a >= spacing and b - beat >= spacing:
                chosen.append(beat)
        lane, step = lane_a, 1                         # flowing back-and-forth lane wave
        for beat in sorted(chosen):
            lane += step
            if lane > 9 or lane < 5:
                step = -step
                lane += 2 * step
            added.append({"beat": round(beat, 4), "key": lane, "datamodel": "custom_custom_spawn_cube/spawn_cube",
                          "width": 0.25, "volume": 100})
    if added:
        merged = list(zip(chart["entities"], axis)) + [(e, 0) for e in added]
        merged.sort(key=lambda pair: (float(pair[0]["beat"]), pair[1]))
        chart["entities"] = [e for e, _ in merged]
        chart["editorMeta"]["axisMap"] = [ax for _, ax in merged]
    return added


# ---------- analysis: how many notes are driven by the singer? ----------

def load_mono(path):
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate != ANALYSIS_RATE:  # simple decimation via linear interpolation; fine for envelopes
        n = int(len(mono) * ANALYSIS_RATE / rate)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype(np.float32)
    return mono


def onset_envelope(signal, hop=110):  # ~10 ms frames
    frames = len(signal) // hop
    rms = np.sqrt(np.mean(signal[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    log_rms = np.log(rms + 1e-5)
    flux = np.maximum(0, np.diff(log_rms, prepend=log_rms[0]))
    return rms, flux


def note_times(chart):
    bpm = float(chart["musicData"]["bpm"])
    return np.array(sorted(float(e["beat"]) * 60 / bpm for e in chart["entities"] if is_note(e)))


def best_lag(times, flux_mix, frame_s=0.01):
    """The generator writes a fixed JSON offset; find the lag that lines notes up with onsets."""
    best = (0.0, -1.0)
    for lag in np.arange(-3.0, 3.0001, 0.01):
        idx = ((times + lag) / frame_s).astype(int)
        idx = idx[(idx >= 0) & (idx < len(flux_mix))]
        score = flux_mix[idx].mean() if len(idx) else 0
        if score > best[1]:
            best = (float(lag), float(score))
    return best[0]


def vocal_driven_share(chart, lag, vocal, inst, frame_s=0.01):
    """A note counts as vocal-driven when the vocal onset there is strong and the
    instrumental has no onset of its own (both measured in a +-40 ms window)."""
    v_rms, v_flux = vocal
    i_rms, i_flux = inst
    v_thr = np.percentile(v_flux[v_rms > np.percentile(v_rms, 50)], 75)
    i_thr = np.percentile(i_flux, 75)
    times = note_times(chart) + lag
    hits = 0
    for t in times:
        a, b = max(0, int((t - 0.04) / frame_s)), int((t + 0.04) / frame_s) + 1
        if b >= len(v_flux):
            continue
        if v_flux[a:b].max() >= v_thr and i_flux[a:b].max() < i_thr:
            hits += 1
    return hits, len(times)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("-d", "--difficulty", type=int, default=2, choices=range(5))
    ap.add_argument("-p", "--pattern", default="frequency", choices=["frequency", "max_sting", "balance"])
    ap.add_argument("--density", type=float, default=1.0)
    ap.add_argument("-t", "--threshold", type=float, default=0.5)
    ap.add_argument("--scene", choices=["city", "forest", "coast", "mountain"])
    ap.add_argument("--device", default="cuda", help="cuda or cpu for Demucs")
    ap.add_argument("--model", default="hdemucs",
                    help="hdemucs = Hybrid Demucs via torchaudio (default); htdemucs / htdemucs_ft = Demucs v4 CLI "
                         "(weights from dl.fbaipublicfiles.com)")
    ap.add_argument("--structure-from", default="full", choices=["full", "instrumental"])
    ap.add_argument("--no-fill", action="store_true", help="don't fill long note gaps during busy music")
    ap.add_argument("--no-lyrics", action="store_true", help="skip lyric transcription")
    ap.add_argument("--language", default="en", help="sung language for Whisper (en, es, ja, ...; '' = auto)")
    ap.add_argument("--lyrics-text", help="official lyrics .txt: skip recognition, only time-align these words")
    ap.add_argument("-o", "--out-dir", help="default: ./charts/<song name>")
    args = ap.parse_args()

    audio = os.path.abspath(args.audio)
    name = os.path.splitext(os.path.basename(audio))[0]
    out_dir = os.path.abspath(args.out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts", name))
    work = os.path.join(out_dir, "_work")
    os.makedirs(work, exist_ok=True)

    vocals, inst = separate(audio, args.device, args.model)
    inst_chart = run_generator(inst, os.path.join(work, "instrumental_chart.json"), args)
    full_chart = run_generator(audio, os.path.join(work, "fullmix_chart.json"), args)
    chart = merge(inst_chart, full_chart if args.structure_from == "full" else None, audio, args.scene)
    filled = [] if args.no_fill else fill_gaps(chart, inst, args.difficulty)
    if filled:
        log(f"gap filler added {len(filled)} notes in empty-but-busy stretches")
    if not args.no_lyrics:
        import lyrics_whisper
        text = open(args.lyrics_text, encoding="utf-8").read() if args.lyrics_text else None
        chart["lyrics"], lyric_lines = lyrics_whisper.lyrics_for(vocals, float(chart["musicData"]["bpm"]), args.language, text, log=log)
        with open(os.path.join(out_dir, "lyrics_words.json"), "w", encoding="utf-8") as fh:
            json.dump(lyric_lines, fh, ensure_ascii=False)

    chart_path = os.path.join(out_dir, "chart.json")
    with open(chart_path, "w", encoding="utf-8") as fh:
        json.dump(chart, fh, ensure_ascii=False)
    write_ogg(audio, os.path.join(out_dir, "audio.ogg"))

    log("analyzing vocal-driven notes...")
    mix_env = onset_envelope(load_mono(audio))
    vocal_env = onset_envelope(load_mono(vocals))
    inst_env = onset_envelope(load_mono(inst))
    lag = best_lag(note_times(full_chart), mix_env[1])
    full_hits, full_n = vocal_driven_share(full_chart, lag, vocal_env, inst_env)
    inst_hits, inst_n = vocal_driven_share(chart, lag, vocal_env, inst_env)
    count = lambda c, kind: sum(1 for e in c["entities"] if e["datamodel"].split("/")[-1] == kind)
    report = {
        "song": name,
        "bpm": {"full_mix": full_chart["musicData"]["bpm"], "instrumental": inst_chart["musicData"]["bpm"]},
        "note_time_lag_s": round(lag, 2),
        "gap_fill_notes_added": len(filled),
        "full_mix_chart": {"cubes": count(full_chart, "spawn_cube"), "cars": count(full_chart, "spawn_sting"),
                           "vocal_driven_notes": full_hits, "share": round(full_hits / max(full_n, 1), 3)},
        "vocal_free_chart": {"cubes": count(chart, "spawn_cube"), "cars": count(chart, "spawn_sting"),
                             "vocal_driven_notes": inst_hits, "share": round(inst_hits / max(inst_n, 1), 3)},
        "files": {"chart": chart_path, "vocals": vocals, "instrumental": inst},
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
