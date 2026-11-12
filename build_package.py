"""Builds the BFS Plus release zips.

  python build_package.py

dist/public/   - for GitHub releases: only BFS Plus's own files (no game files)
    BFS-Plus-<version>.zip          installer (Install BFS Plus.bat)
    BFS-Plus-<version>-manual.zip   no scripts: files to copy + 6 lines to paste into the editor page
dist/friends/  - private, for friends: also includes the upgraded Lyrics Assistant (modified copies of the
                 game's lyrics.js / recognition worker) and, in the manual zip, a ready-hooked editor page.
                 Not for public posting.

Never includes .env, API keys, songs, recordings or local paths - the build stops if it finds any.
"""
import hashlib
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.0.0"
NAME = f"BFS-Plus-{VERSION}"
DIST = os.path.join(ROOT, "dist")

ADD_ON_FILES = ["accessibility.js", "editor_plus.css", "editor_plus_i18n.js", "lyric_tap_sync.js", "lyric3d_store.js",
                "lyric_designer.js"]
UPGRADED_GAME_FILES = ["lyrics.js", "lyric_recognition_worker.js"]   # modified copies of the game's files: friends only
CREATOR_FILES = {
    "chart_pipeline": ["make_chart.py", "lyrics_whisper.py", "paths.py", "make_chart.bat"],
    "ai_director": ["director.py", "budget.py", "style_profile.py", "catalog_from_game.py"],
    "lyric_director": ["lyric_director.py"],
    "lyric_fx": ["lyric_fx.py"],
    "tools": ["discord_clip.py", "Discord Clip (drag video here).bat"],
}
FORBIDDEN = [r"sk-ant-[A-Za-z0-9_-]{10,}", r"\btanne\b", r"tan2019", r"beatspeeder-env", r"SteamLibraryssd"]
SCRIPT_EXTENSIONS = (".bat", ".ps1", ".cmd", ".vbs", ".exe")
GAME_FILE_NAMES = UPGRADED_GAME_FILES + ["chart_editor.html", "based_on.txt", "catalog.json"]


def copy(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(source, destination)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def write_readme(variant, destination):
    text = open(os.path.join(ROOT, "package", "README.txt"), encoding="utf-8").read()
    if variant == "public":
        text = text.replace("* Better LYRICS ASSISTANT - stronger local speech recognition to time lyrics, plus \"tap to sync\".",
                            "* TAP TO SYNC in the Lyrics Assistant - press Enter as each line starts to time lyrics by hand.")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    open(destination, "w", encoding="utf-8").write(text)


def copy_editor_files(variant, stage, hooked_page):
    for name in ADD_ON_FILES:
        copy(os.path.join(ROOT, "mod", name), os.path.join(stage, "editor", name))
    if variant != "friends":
        return
    for name in UPGRADED_GAME_FILES:
        copy(os.path.join(ROOT, "mod", name), os.path.join(stage, "editor", name))
    if hooked_page:
        page = os.path.join(ROOT, "package", "manual", "chart_editor.html")
        if not os.path.exists(page):
            raise SystemExit("package/manual/chart_editor.html missing - copy it from a game where install.ps1 ran")
        copy(page, os.path.join(stage, "editor", "chart_editor.html"))


def stage_installer(variant, stage):
    for name in ("install.ps1", "uninstall.ps1", "Install BFS Plus.bat", "Uninstall BFS Plus.bat"):
        copy(os.path.join(ROOT, "package", name), os.path.join(stage, name))
    copy(os.path.join(ROOT, "find_game.ps1"), os.path.join(stage, "find_game.ps1"))
    write_readme(variant, os.path.join(stage, "README.txt"))
    open(os.path.join(stage, "VERSION"), "w").write(VERSION + "\n")
    copy_editor_files(variant, stage, hooked_page=False)
    if variant == "friends":
        # the game's versions the upgraded files were made from: the installer only swaps them in on an exact match
        with open(os.path.join(stage, "editor", "based_on.txt"), "w") as handle:
            for name in UPGRADED_GAME_FILES:
                handle.write(f"{sha256(os.path.join(ROOT, 'original', name))} {name}\n")
    copy(os.path.join(ROOT, "lyric3d", "plugin", "bin", "Release", "net6.0", "BfsLyric3D.dll"),
         os.path.join(stage, "game-mod", "BfsLyric3D.dll"))
    for folder, names in CREATOR_FILES.items():
        for name in names:
            copy(os.path.join(ROOT, folder, name), os.path.join(stage, "creator-tools", folder, name))
    for name in ("CREATOR_TOOLS.md", "requirements.txt", ".env.example"):
        copy(os.path.join(ROOT, "package", "creator-tools", name), os.path.join(stage, "creator-tools", name))


def stage_manual(variant, stage, installer_stage):
    write_readme(variant, os.path.join(stage, "README.txt"))
    guide = "MANUAL-INSTALL.txt" if variant == "friends" else "MANUAL-INSTALL-public.txt"
    copy(os.path.join(ROOT, "package", guide), os.path.join(stage, "MANUAL-INSTALL.txt"))
    copy(os.path.join(installer_stage, "game-mod", "BfsLyric3D.dll"), os.path.join(stage, "game-mod", "BfsLyric3D.dll"))
    copy_editor_files(variant, stage, hooked_page=True)


def check(stage, variant, manual):
    problems = []
    for folder, _, files in os.walk(stage):
        for name in files:
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, stage)
            lower = name.lower()
            if lower.endswith((".mp3", ".ogg", ".wav", ".mp4", ".mkv")) or name == ".env":
                problems.append(f"media/secret file: {relative}")
                continue
            if manual and lower.endswith(SCRIPT_EXTENSIONS):
                problems.append(f"script in the manual zip: {relative}")
            if variant == "public" and name in GAME_FILE_NAMES:
                problems.append(f"game file in the public build: {relative}")
            if lower.endswith(".dll"):
                continue
            text = open(path, encoding="utf-8", errors="ignore").read()
            for pattern in FORBIDDEN:
                if re.search(pattern, text, re.IGNORECASE):
                    problems.append(f"{relative} contains /{pattern}/")
    if problems:
        raise SystemExit("NOT packaged:\n  " + "\n  ".join(problems))


def write_zip(zip_path, stage, top):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, _, files in os.walk(stage):
            for name in files:
                path = os.path.join(folder, name)
                archive.write(path, os.path.join(top, os.path.relpath(path, stage)))
    count = sum(len(files) for _, _, files in os.walk(stage))
    print(f"{os.path.relpath(zip_path, ROOT)}: {count} files, {os.path.getsize(zip_path) / 1e6:.2f} MB")


def build(variant):
    out = os.path.join(DIST, variant)
    installer_stage = os.path.join(out, NAME)
    manual_stage = os.path.join(out, NAME + "-manual")
    for stage in (installer_stage, manual_stage):
        shutil.rmtree(stage, ignore_errors=True)
    stage_installer(variant, installer_stage)
    stage_manual(variant, manual_stage, installer_stage)
    check(installer_stage, variant, manual=False)
    check(manual_stage, variant, manual=True)
    write_zip(os.path.join(out, NAME + ".zip"), installer_stage, NAME)
    write_zip(os.path.join(out, NAME + "-manual.zip"), manual_stage, NAME + "-manual")


def main():
    if os.path.isdir(DIST):   # clear older single-variant builds
        for old in os.listdir(DIST):
            path = os.path.join(DIST, old)
            if old.startswith("BFS-Plus-"):
                shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
    build("public")
    build("friends")


if __name__ == "__main__":
    main()
