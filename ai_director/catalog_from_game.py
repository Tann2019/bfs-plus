"""The game's chart event types (datamodels), read from the chart editor in YOUR game install.

The AI director needs the list of events it may place (themes, camera, speed, ramps...). Instead of shipping
the game's data, this reads it from Tools/chart_editor each time:
  * chart_editor.html - the DEFAULT_DATAMODEL_TYPES entries and the named groups ("Common", "City Theme", ...)
  * locales.js        - the English names and descriptions the editor shows (theme names only live there)
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chart_pipeline"))
import paths  # noqa: E402

USABLE_GROUPS = ("Common", "City Theme", "Forest Theme", "Coast Theme", "Mountain Theme")   # what a chart designer places
QUOTED = r'"((?:[^"\\]|\\.)*)"'
ENTRY = re.compile(r'^\s*\{\s*"?datamodel"?\s*:\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Z_][A-Z0-9_]*))(.*)$')
GROUP = re.compile(r'\{\s*"?name"?\s*:\s*"([^"]+)"\s*,\s*"?datamodels"?\s*:\s*\[([^\]]*)\]')
LOCALE_TEXT = re.compile(r'"(type\.[^"]+\.(?:label|description))"\s*:\s*' + QUOTED)


def _editor_folder():
    return os.path.join(paths.game_dir(), "Tools", "chart_editor")


def _editor_html():
    folder = _editor_folder()
    # the game's own copy if BFS Plus backed it up (the event list is the same either way)
    for candidate in (os.path.join(folder, "_bfs_plus_backup", "chart_editor.html"), os.path.join(folder, "chart_editor.html")):
        if os.path.exists(candidate):
            return open(candidate, encoding="utf-8", errors="ignore").read()
    raise SystemExit("chart_editor.html not found in the game folder")


def _english_texts():
    """'type.<datamodel>.label' / '.description' from the "en" block of locales.js."""
    path = os.path.join(_editor_folder(), "locales.js")
    if not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8", errors="ignore").read()
    start = text.find('"en": {')
    if start < 0:
        return {}
    end = text.find('"zh_cn": {', start)
    return dict(LOCALE_TEXT.findall(text[start:end if end > 0 else len(text)]))


def _field(name, text):
    match = re.search(r'(?<![A-Za-z])' + name + r'\s*:\s*' + QUOTED, text)
    return match.group(1) if match else None


def load_catalog():
    """[{datamodel, group, label, description}, ...] in the editor's order."""
    html = _editor_html()
    constants = dict(re.findall(r"const ([A-Z_][A-Z0-9_]*_DATAMODEL)\s*=\s*['\"]([^'\"]+)['\"]", html))
    start = html.index("const DEFAULT_DATAMODEL_TYPES = [")
    block = html[start:html.index("\n];", start)]
    english = _english_texts()

    types = []
    for line in block.splitlines()[1:]:
        match = ENTRY.match(line)
        if not match:
            continue
        datamodel = match.group(1) or match.group(2) or constants.get(match.group(3), "")
        if not datamodel:
            continue
        rest = match.group(4)
        label = english.get(f"type.{datamodel}.label") or _field("label", rest) or datamodel.split("/")[-1]
        description = english.get(f"type.{datamodel}.description") or _field("description", rest) or ""
        types.append({"datamodel": datamodel, "label": label, "description": description})

    groups = {}
    for name, members in GROUP.findall(html[start:]):
        for quoted, constant in re.findall(r'"([^"]+)"|([A-Z_][A-Z0-9_]*_DATAMODEL)', members):
            member = quoted or constants.get(constant, "")
            if member:
                groups.setdefault(member, name)
    return [{"datamodel": t["datamodel"], "group": groups[t["datamodel"]], "label": t["label"], "description": t["description"]}
            for t in types if groups.get(t["datamodel"]) in USABLE_GROUPS]


if __name__ == "__main__":
    for entry in load_catalog():
        print(f"{entry['group']:15s} {entry['datamodel']:50s} {entry['label']}")
