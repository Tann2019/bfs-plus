"""Where things live, on any PC: the game (found through Steam), its Workshop folder, and a work folder
for big downloads and caches (Whisper/Demucs models, separated stems).

Override with environment variables: BFS_GAME_DIR, BFS_WORKSHOP_DIR, BFS_WORK_DIR.
"""
import os
import re

APP_ID = "4430260"   # Beat For Speed on Steam
TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _steam_libraries():
    roots = []
    try:
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(winreg.QueryValueEx(handle, value)[0])
            except OSError:
                pass
    except ImportError:
        pass
    libraries = []
    for root in roots:
        libraries.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            text = open(vdf, encoding="utf-8", errors="ignore").read()
            libraries += [path.replace("\\\\", "\\") for path in re.findall(r'"path"\s+"([^"]+)"', text)]
    return list(dict.fromkeys(libraries))


def game_dir():
    if os.environ.get("BFS_GAME_DIR"):
        return os.environ["BFS_GAME_DIR"]
    for library in _steam_libraries():
        candidate = os.path.join(library, "steamapps", "common", "Beat For Speed")
        if os.path.exists(os.path.join(candidate, "Tools", "chart_editor", "chart_editor.html")):
            return candidate
    raise SystemExit("Beat For Speed not found through Steam - set BFS_GAME_DIR to the game folder")


def workshop_dir():
    if os.environ.get("BFS_WORKSHOP_DIR"):
        return os.environ["BFS_WORKSHOP_DIR"]
    try:
        library = os.path.dirname(os.path.dirname(os.path.dirname(game_dir())))   # ...\steamapps\common\<game> -> library
        return os.path.join(library, "steamapps", "workshop", "content", APP_ID)
    except SystemExit:
        return ""


def work_dir():
    """Big caches go here (several GB): BFS_WORK_DIR, else the folder named in work_dir.txt next to the
    tools, else ./work."""
    path = os.environ.get("BFS_WORK_DIR")
    pointer = os.path.join(TOOLS_ROOT, "work_dir.txt")
    if not path and os.path.exists(pointer):
        path = open(pointer, encoding="utf-8").read().strip()
    path = path or os.path.join(TOOLS_ROOT, "work")
    os.makedirs(path, exist_ok=True)
    return path


def use_work_dir_for_model_caches():
    """Keep PyTorch / Hugging Face downloads in the work folder instead of the (often full) C: drive."""
    os.environ.setdefault("TORCH_HOME", os.path.join(work_dir(), "torch"))
    os.environ.setdefault("HF_HOME", os.path.join(work_dir(), "hf"))
