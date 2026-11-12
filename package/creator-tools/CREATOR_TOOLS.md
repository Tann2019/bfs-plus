# BFS Plus creator tools (optional, advanced)

Command-line tools that turn a song into a full chart. Not needed to play or to use the editor.
Needs Windows, Python 3.11, and ideally an NVIDIA GPU (CPU works, slowly). Models download on first use
(several GB) into `work/` here - or set `BFS_WORK_DIR` to a drive with space.

## Setup
1. `pip install` as described at the top of `requirements.txt`.
2. For the AI tools: copy `.env.example` to `.env` and put in **your own** Anthropic API key.
   Each AI run costs well under $1; the tools keep a running total and stop at `--budget` (default $30).

## 1. Make a chart from a song
    python chart_pipeline/make_chart.py "song.mp3" -d 2 --scene city
Separates vocals from the music (Demucs), charts notes from the instrumental with the game's own
generator, transcribes and times the lyrics (Whisper large-v3 + word alignment). Optional:
`--lyrics-text lyrics.txt` uses lyrics you provide (only the timing is computed). Output: a folder in
`chart_pipeline/charts/<song>` with `chart.json`, the audio and a report.

## 2. AI director (Claude) - notes, cars, scenery, events
    python ai_director/director.py "chart_pipeline/charts/<song>" --difficulty 2 --effort high
Fits the song's exact tempo from the drums, finds the drops, then Claude plans every phrase (which
instrument the notes follow, lane patterns, cars, doubles, bonus notes, ramps, theme/camera/speed events)
and reviews its own result. Writes `chart_directed.json` (+ `audio_aligned.ogg` when the song needed a
tiny bit of silence to sit on the beat grid - use that audio file with the chart).

## 3. Lyric director (Claude) - 3D signs
    python lyric_director/lyric_director.py "<song folder>/chart_directed.json" --vocals "<stems>/vocals.wav" --audio "<song folder>/audio.mp3" --out "<song folder>/final.json"
Fixes misheard words, splits phrases where the singer breathes, and designs every 3D sign (line breaks,
emphasis, colours, fonts, subtle entrances, big moments on the drops).

## 4. Into the game
Open the chart editor from the game, load the audio (.ogg) and the chart (.json), check it in the
3D Lyric Designer, then Import to Game or Upload to Workshop.

## Extra
`tools/Discord Clip (drag video here).bat` - drag an OBS recording onto it for a copy under 50 MB
(auto-crops black bars, e.g. ultrawide). `python tools/discord_clip.py clip.mp4 --size 10 --start 1:05 --end 1:45`.
