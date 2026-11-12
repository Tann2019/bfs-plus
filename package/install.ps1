# BFS Plus installer: upgrades the Beat For Speed chart editor and installs the 3D lyrics game mod.
# Safe to run again (e.g. after a game update). Undo everything with "Uninstall BFS Plus.bat".
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
. (Join-Path $here 'find_game.ps1')
$version = (Get-Content (Join-Path $here 'VERSION') -Raw).Trim()
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }

Say "BFS Plus $version installer" 'Cyan'

# ---------------------------------------------------------------- find the game
$game = Find-GameDir
if (-not $game) {
  $game = Read-Host 'Could not find Beat For Speed through Steam. Paste the game folder path'
  if (-not (Test-Path (Join-Path $game 'Tools\chart_editor\chart_editor.html'))) { throw "That folder does not look like Beat For Speed: $game" }
}
Say "Game: $game"
if (Get-Process -Name 'beatforspeed' -ErrorAction SilentlyContinue) {
  Say 'Please close Beat For Speed first, then run this again.' 'Yellow'
  exit 1
}

$editor = Join-Path $game 'Tools\chart_editor'
$backup = Join-Path $editor '_bfs_plus_backup'
New-Item -ItemType Directory -Force $backup | Out-Null

# ---------------------------------------------------------------- 1. back up the game's own files
# Only files that are still the game's (not already modded) are backed up, so a game update's new
# versions replace older backups.
function Is-Modded($path) {
  $name = Split-Path $path -Leaf
  $packaged = Join-Path $here "editor\$name"
  if ((Test-Path $packaged) -and (Get-FileHash $path).Hash -eq (Get-FileHash $packaged).Hash) { return $true }
  $text = [IO.File]::ReadAllText($path)
  # markers from any BFS Plus version: html hooks, the upgraded lyrics.js, the upgraded recognition worker
  return $text.Contains('BFS Plus') -or $text.Contains('editor_plus') -or $text.Contains('LYRIC_AI_MODELS') -or $text.Contains('planVoiceWindows')
}
foreach ($name in 'chart_editor.html', 'lyrics.js', 'lyric_recognition_worker.js') {
  $path = Join-Path $editor $name
  if ((Test-Path $path) -and -not (Is-Modded $path)) { Copy-Item $path (Join-Path $backup $name) -Force }
}
$stockHtml = Join-Path $backup 'chart_editor.html'
if (-not (Test-Path $stockHtml)) { throw "No clean copy of chart_editor.html found. Verify the game files in Steam and run this again." }

# ---------------------------------------------------------------- 2. add-on files
$addOns = 'accessibility.js', 'editor_plus.css', 'editor_plus_i18n.js', 'lyric_tap_sync.js', 'lyric3d_store.js', 'lyric_designer.js'
foreach ($name in $addOns) { Copy-Item (Join-Path $here "editor\$name") (Join-Path $editor $name) -Force }
Say "  added the 3D Lyric Designer, accessibility options and tap sync" 'Green'

# ---------------------------------------------------------------- 3. upgraded lyric recognition (only on the editor version it was made for)
# The public build has no Lyrics Assistant upgrade (those two files are the game's, modified): keep the game's own.
$hasUpgrade = (Test-Path (Join-Path $here 'editor\lyrics.js')) -and (Test-Path (Join-Path $here 'editor\based_on.txt'))
$basedOn = @{}
if ($hasUpgrade) {
  foreach ($line in Get-Content (Join-Path $here 'editor\based_on.txt')) { $parts = $line -split '\s+', 2; if ($parts.Count -eq 2) { $basedOn[$parts[1]] = $parts[0] } }
}
$replacedLyrics = $hasUpgrade
foreach ($name in 'lyrics.js', 'lyric_recognition_worker.js') {
  $stock = Join-Path $backup $name
  if (-not (Test-Path $stock) -or (Get-FileHash $stock -Algorithm SHA256).Hash.ToLower() -ne $basedOn[$name]) { $replacedLyrics = $false }
}
if ($replacedLyrics) {
  foreach ($name in 'lyrics.js', 'lyric_recognition_worker.js') { Copy-Item (Join-Path $here "editor\$name") (Join-Path $editor $name) -Force }
  Say "  upgraded the Lyrics Assistant (better local speech recognition)" 'Green'
} else {
  foreach ($name in 'lyrics.js', 'lyric_recognition_worker.js') { if (Test-Path (Join-Path $backup $name)) { Copy-Item (Join-Path $backup $name) (Join-Path $editor $name) -Force } }
  if ($hasUpgrade) { Say "  the game's editor is newer than this BFS Plus: kept its own Lyrics Assistant (everything else still works)" 'Yellow' }
  else { Say "  kept the game's own Lyrics Assistant (the upgraded one is not part of this build)" }
}

# ---------------------------------------------------------------- 4. hook the add-ons into the game's chart_editor.html
$html = [IO.File]::ReadAllText($stockHtml)
$tag = "bfsplus-$version"
function Insert-After([string]$text, [string]$pattern, [string]$addition, [string]$what) {
  $match = [regex]::Match($text, $pattern)
  if (-not $match.Success) { Say "  note: could not find $what in the editor - skipped" 'Yellow'; return $text }
  return $text.Insert($match.Index + $match.Length, $addition)
}
$html = $html -replace '</head>', "<link rel=`"stylesheet`" href=`"editor_plus.css?v=$tag`"><!-- BFS Plus -->`n</head>"
$html = Insert-After $html '<script src="locales\.js[^"]*"></script>' "`n<script src=`"editor_plus_i18n.js?v=$tag`"></script><!-- BFS Plus -->" 'the language file'
if ($replacedLyrics) { $html = $html -replace '<script src="lyrics\.js[^"]*"></script>', "<script src=`"lyrics.js?v=$tag`"></script>" }
$html = Insert-After $html '<script src="lyrics\.js[^"]*"></script>' "`n<script src=`"lyric3d_store.js?v=$tag`"></script><!-- BFS Plus -->" 'the lyrics script'
$bodyEnd = $html.LastIndexOf('</body>')
if ($bodyEnd -lt 0) { throw 'Unexpected chart_editor.html (no </body>)' }
$html = $html.Insert($bodyEnd, "<!-- BFS Plus -->`n<script src=`"accessibility.js?v=$tag`"></script>`n<script src=`"lyric_tap_sync.js?v=$tag`"></script>`n<script src=`"lyric_designer.js?v=$tag`"></script>`n")
# optional larger text (Settings > Accessibility): read by the editor's own viewport code
$scaleLine = "`n  try { const saved = Number(localStorage.getItem('chart_editor_ui_scale')); if(localStorage.getItem('chart_editor_a11y') === 'true' && saved >= 1 && saved <= 2) editorScale = saved; } catch {} // BFS Plus"
$html = Insert-After $html 'function updateEditorViewport\(\)\{\s*\r?\n\s*editorScale = 1;' $scaleLine 'the editor zoom code (text size option)'
[IO.File]::WriteAllText((Join-Path $editor 'chart_editor.html'), $html, $utf8)
Say "  chart editor updated (open it from the game; press Ctrl+F5 if it was already open)" 'Green'

# ---------------------------------------------------------------- 5. the in-game 3D lyrics mod (needs MelonLoader)
$melonDll = Join-Path $game 'MelonLoader\net6\MelonLoader.dll'
if (-not (Test-Path $melonDll)) {
  Say ''
  Say 'The 3D lyrics in game need MelonLoader 0.7.3 (the standard Unity mod loader, open source).' 'Cyan'
  $answer = Read-Host 'Download and install it now from github.com/LavaGang/MelonLoader? [Y/n]'
  if ($answer -match '^(n|no)$') {
    Say 'Skipped. The editor upgrades are installed; 3D lyrics will not show in game until MelonLoader is installed.' 'Yellow'
    Say 'Done.' 'Cyan'; exit 0
  }
  $zip = Join-Path $env:TEMP 'MelonLoader.x64.0.7.3.zip'
  Say '  downloading MelonLoader 0.7.3...'
  Invoke-WebRequest 'https://github.com/LavaGang/MelonLoader/releases/download/v0.7.3/MelonLoader.x64.zip' -OutFile $zip -UseBasicParsing
  $listing = Join-Path $game 'Mods\BfsPlus_melonloader_files.txt'
  New-Item -ItemType Directory -Force (Join-Path $game 'Mods') | Out-Null
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [IO.Compression.ZipFile]::OpenRead($zip)
  $installed = @()
  try {
    foreach ($entry in $archive.Entries) {
      $target = Join-Path $game $entry.FullName
      if ($entry.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force $target | Out-Null; continue }
      New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
      [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
      $installed += $entry.FullName
    }
  } finally { $archive.Dispose() }
  Set-Content $listing $installed -Encoding UTF8
  Remove-Item $zip -Force
  Say '  MelonLoader installed. The first game start takes a few extra minutes while it sets up.' 'Green'
}
New-Item -ItemType Directory -Force (Join-Path $game 'Mods') | Out-Null
Copy-Item (Join-Path $here 'game-mod\BfsLyric3D.dll') (Join-Path $game 'Mods\BfsLyric3D.dll') -Force
Say '  3D lyrics game mod installed (settings: UserData\MelonPreferences.cfg, section [BfsLyric3D])' 'Green'
Say ''
Say 'Done! Start Beat For Speed; songs with lyrics now show them as 3D signs beside the road.' 'Cyan'
