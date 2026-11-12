"""Native GPU lyric transcription + word alignment for Beat For Speed charts.

  1. faster-whisper (CTranslate2) running Whisper large-v3 in float16 on the GPU,
     beam search; VAD off (it mistakes separated vocal stems for silence).
  2. Word timing refined by CTC forced alignment with torchaudio's English wav2vec2 model,
     the same approach WhisperX uses for English. Words the aligner can't handle keep Whisper's times.
  3. Words grouped into display lines at pauses / sentence ends / ~40 characters.

Use on the isolated vocal stem from make_chart.py for best results. Optionally pass the
official lyrics as a text file to skip recognition and only align (most accurate words).
"""
import os
import re
import unicodedata

import numpy as np
import soundfile as sf
import torch

os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))  # cuBLAS/cuDNN for CTranslate2

import paths  # noqa: E402  (same folder)

WHISPER_DIR = os.environ.get("BFS_WHISPER_DIR", os.path.join(paths.work_dir(), "whisper"))
RATE = 16000


def load_16k(path):
    import torchaudio.functional as AF
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = torch.from_numpy(data.mean(axis=1))
    if rate != RATE:
        mono = AF.resample(mono, rate, RATE)
    return mono.numpy()


# Whisper was trained on lots of subtitled video, so over instrumentals and song endings it tends to
# "hear" subtitle credits and sign-offs. Segments matching these are dropped.
HALLUCINATION_PATTERN = re.compile(
    r"(transcri(pt|bed|ption)\b|subtitles?\b|captions?\b|amara\.org|©|copyright|all rights reserved|"
    r"thanks? (you )?for watching|please subscribe|like and subscribe|字幕|ご視聴|시청해)",
    re.IGNORECASE)


def is_hallucination(text):
    return bool(HALLUCINATION_PATTERN.search(text or ""))


def transcribe(audio, language="en", model_name="large-v3", device="cuda", log=print):
    from faster_whisper import WhisperModel
    log(f"loading Whisper {model_name} ({device}, float16)...")
    model = WhisperModel(model_name, device=device, compute_type="float16" if device == "cuda" else "int8",
                         download_root=WHISPER_DIR)
    # No VAD: Silero VAD treats separated vocal stems as silence and drops most of the song.
    segments, info = model.transcribe(
        audio, language=language or None, task="transcribe", beam_size=5,
        word_timestamps=True, no_speech_threshold=0.6,
    )
    words = []
    dropped = 0
    for segment in segments:
        if is_hallucination(segment.text) or (segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0):
            dropped += 1
            continue
        for word in segment.words or []:
            text = word.word.strip()
            if text:
                words.append({"start": float(word.start), "end": float(word.end), "text": text, "prob": float(word.probability)})
    log(f"Whisper heard {len(words)} words (language: {info.language}, p={info.language_probability:.2f})"
        + (f"; dropped {dropped} hallucinated/non-speech segments" if dropped else ""))
    return words


def _align_key(word):
    """wav2vec2-960h labels are A-Z and apostrophe; romanize accents, drop everything else."""
    plain = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z']", "", plain)


def force_align(audio, words, device="cuda", log=print):
    """Refine word times with CTC forced alignment (English wav2vec2, as WhisperX does for English),
    phrase by phrase. Weights come from download.pytorch.org."""
    import torchaudio
    import torchaudio.functional as AF
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = bundle.get_model().to(device).eval()
    labels = bundle.get_labels()                     # ('-', '|', 'E', 'T', ...): blank=0, word sep='|'
    index = {c: i for i, c in enumerate(labels)}
    phrases, current = [], []
    for w in words:
        if current and w["start"] - current[-1]["end"] > 1.0:
            phrases.append(current)
            current = []
        current.append(w)
    if current:
        phrases.append(current)
    refined = 0
    for phrase in phrases:
        keys = [_align_key(w["text"]) for w in phrase]
        usable = [i for i, k in enumerate(keys) if k]
        if not usable:
            continue
        a = max(0.0, phrase[0]["start"] - 0.5)
        b = min(len(audio) / RATE, phrase[-1]["end"] + 0.5)
        clip = torch.from_numpy(audio[int(a * RATE):int(b * RATE)]).unsqueeze(0).to(device)
        if clip.shape[1] < RATE // 4:
            continue
        with torch.inference_mode():
            emission, _ = model(clip)
            emission = torch.log_softmax(emission, dim=-1)
        transcript = "|".join(keys[i] for i in usable)
        targets = torch.tensor([[index[c] for c in transcript]], dtype=torch.int32, device=device)
        if targets.shape[1] > emission.shape[1]:
            continue                                  # more letters than audio frames: can't align
        try:
            aligned, scores = AF.forced_align(emission, targets, blank=0)
        except Exception:
            continue
        spans = AF.merge_tokens(aligned[0], scores[0].exp())
        frame = clip.shape[1] / emission.shape[1] / RATE
        # split token spans into words at the '|' separators
        sep = index["|"]
        word_spans, cur = [], []
        for span in spans:
            if span.token == sep:
                if cur:
                    word_spans.append(cur)
                cur = []
            else:
                cur.append(span)
        if cur:
            word_spans.append(cur)
        if len(word_spans) != len(usable):
            continue
        for i, ws in zip(usable, word_spans):
            phrase[i]["start"] = a + ws[0].start * frame
            phrase[i]["end"] = a + ws[-1].end * frame
            refined += 1
    log(f"forced alignment refined {refined}/{len(words)} word times")
    return words


def words_from_text(text):
    """Official lyrics -> word list (no timing yet); section labels like [Chorus] are dropped."""
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l and not re.match(r"^[\[(].*[\])]$", l)]
    return [{"text": w, "line_break": i == len(line.split()) - 1}
            for line in lines for i, w in enumerate(line.split())]


def group_lines(words, max_chars=40, pause=0.55):
    lines, current = [], []
    for w in words:
        if current:
            text_len = len(" ".join(x["text"] for x in current))
            if (w["start"] - current[-1]["end"] > pause or text_len >= max_chars
                    or re.search(r"[.!?。！？]$", current[-1]["text"]) or current[-1].get("line_break")):
                lines.append(current)
                current = []
        current.append(w)
    if current:
        lines.append(current)
    out = []
    for line in lines:
        text = " ".join(w["text"] for w in line)
        text = re.sub(r"\s+([,.!?])", r"\1", text).strip()
        out.append({"start": line[0]["start"], "end": max(line[-1]["end"], line[0]["start"] + 0.3), "text": text,
                    "words": [{"start": w["start"], "end": w["end"], "text": w["text"]} for w in line if "start" in w]})
    # never overlap the next line
    for cur, nxt in zip(out, out[1:]):
        cur["end"] = min(cur["end"], nxt["start"] - 0.05)
    return out


def to_chart_lyrics(lines, bpm, row=1):
    beats = bpm / 60.0
    return [{"beat": round(l["start"] * beats, 4), "duration": round(max(0.05, (l["end"] - l["start"]) * beats), 4),
             "text": l["text"], "row": row, "syncConfidence": "high"} for l in lines]


def lyrics_for(vocals_path, bpm, language="en", lyrics_text=None, log=print):
    audio = load_16k(vocals_path)
    if lyrics_text:
        # Official text: get rough times from Whisper, then map the official words onto them in order.
        heard = transcribe(audio, language, log=log)
        official = words_from_text(lyrics_text)
        if heard:
            times = np.linspace(0, len(heard) - 1, num=len(official)).round().astype(int)
            for w, idx in zip(official, times):
                w["start"], w["end"] = heard[idx]["start"], heard[idx]["end"]
        words = force_align(audio, official, log=log)
    else:
        words = force_align(audio, transcribe(audio, language, log=log), log=log)
    lines = group_lines(words)
    log(f"{len(lines)} lyric lines")
    return to_chart_lyrics(lines, bpm), lines
