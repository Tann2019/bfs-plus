# BFS Plus

A community mod for **Beat For Speed**: song lyrics as 3D signs beside the road, a 3D Lyric Designer in
the chart editor, accessibility options, and optional AI tools that turn a song into a full chart.

Not affiliated with the developers of Beat For Speed.

## Features

- **3D lyrics in game.** Lyrics appear as big signs beside the road. They light up word by word as they are
  sung (karaoke), or type in like a typewriter, and they fade, dissolve or rise away as you drive past.
  This works with any chart that has lyrics, including other people's Workshop charts.
- **3D Lyric Designer** in the chart editor:
  - design each sign's text, colours, fonts, size and animations
  - set when the karaoke or typewriter starts and ends
  - place signs beside the road (drag them along it), or anywhere in the world, stuck onto building walls
  - ride along with the song, with time labels on the road and a scrubber
- **Accessibility** (Settings > Accessibility mode): bigger text, focus outlines, high contrast, reduced
  motion, and a keyboard shortcut list (press `?` or F1).
- **Tap to sync**: time lyrics by pressing Enter as each line starts.
- **Creator tools** (optional, advanced): Python tools that separate vocals, chart notes, transcribe and
  time lyrics, then have Claude direct the chart and design the 3D lyrics. Bring your own Anthropic API key.

Charts made with the designer work for **everyone**. Players with BFS Plus see the 3D signs, and players
without it see the game's normal lyrics.

## Install

Download from [Releases](../../releases):

- **BFS-Plus-x.y.z-Setup.exe**: a normal setup wizard. It finds the game through Steam, offers to download
  [MelonLoader](https://github.com/LavaGang/MelonLoader) 0.7.3 if needed, and appears in Windows Settings
  > Apps for uninstalling. It isn't code-signed, so Windows may show "Windows protected your PC": choose
  "More info" > "Run anyway".
- **BFS-Plus-x.y.z.zip**: the same install as a script. Close the game, unzip, then double-click
  `Install BFS Plus.bat`. Run it again after a game update.
- **BFS-Plus-x.y.z-manual.zip**: no scripts at all, in case your browser or antivirus blocks the
  installer. Follow `MANUAL-INSTALL.txt`.

`README.txt` in the zip explains how to use everything.

## Repository layout

| Folder | What |
|---|---|
| `mod/` | Chart editor add-ons: `lyric_designer.js` (3D designer), `lyric3d_store.js` (saving and loading the design), `accessibility.js`, `lyric_tap_sync.js`, `editor_plus.css`, `editor_plus_i18n.js` |
| `lyric3d/plugin/` | The in-game mod (MelonLoader, C#, net6) |
| `package/` | Installers (script and Inno Setup wizard `BFS-Plus.iss`), uninstaller and user docs |
| `chart_pipeline/` | Song → chart: vocal separation, the game's chart generator, Whisper lyrics |
| `ai_director/` | Claude plans the chart (tempo fit, drops, phrases, events) |
| `lyric_director/` | Claude cleans up lyrics and designs the 3D signs |
| `lyric_fx/`, `tools/` | Lyric colour presets; Discord-size video clipper |

The editor add-ons hook into the game's own editor from the outside. They never replace its files, so
they keep working when the game updates. None of the game's files are in this repository.

## Building

- **Game mod:** .NET 6 SDK, plus the game with MelonLoader installed and started once. Put your game path in
  `lyric3d/plugin/GameDir.local.props`, or pass `-p:GameDir="..."`. Then run
  `dotnet build lyric3d/plugin -c Release`.
- **Release files:** `python build_package.py` writes the zips and, if [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed, the setup exe to `dist/public/`.
- **Creator tools:** see `package/creator-tools/CREATOR_TOOLS.md`.

## Credits

- [MelonLoader](https://github.com/LavaGang/MelonLoader) (Apache-2.0), which loads the in-game mod. The installer downloads it from its official releases.
- Speech recognition: [Whisper](https://github.com/openai/whisper) via faster-whisper and transformers.js. Vocal separation: Demucs (torchaudio).
- Beat For Speed © its developers. BFS Plus is an unofficial fan mod.

## License

MIT, see [LICENSE](LICENSE).
