# Removes BFS Plus: restores the game's own chart editor files and removes the 3D lyrics mod.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
. (Join-Path $here 'find_game.ps1')
function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }

$game = Find-GameDir
if (-not $game) { $game = Read-Host 'Could not find Beat For Speed through Steam. Paste the game folder path' }
if (Get-Process -Name 'beatforspeed' -ErrorAction SilentlyContinue) { Say 'Please close Beat For Speed first.' 'Yellow'; exit 1 }

$editor = Join-Path $game 'Tools\chart_editor'
$backup = Join-Path $editor '_bfs_plus_backup'
foreach ($name in 'chart_editor.html', 'lyrics.js', 'lyric_recognition_worker.js') {
  $saved = Join-Path $backup $name
  if (Test-Path $saved) { Copy-Item $saved (Join-Path $editor $name) -Force }
}
foreach ($name in 'accessibility.js', 'editor_plus.css', 'editor_plus_i18n.js', 'lyric_tap_sync.js', 'lyric3d_store.js', 'lyric_designer.js') {
  Remove-Item (Join-Path $editor $name) -ErrorAction SilentlyContinue
}
Remove-Item $backup -Recurse -ErrorAction SilentlyContinue
Say 'Chart editor restored to the game version.' 'Green'

Remove-Item (Join-Path $game 'Mods\BfsLyric3D.dll') -ErrorAction SilentlyContinue
Say '3D lyrics mod removed.' 'Green'

$listing = Join-Path $game 'Mods\BfsPlus_melonloader_files.txt'
if (Test-Path $listing) {
  $answer = Read-Host 'BFS Plus installed MelonLoader. Remove it too (only if no other mods need it)? [y/N]'
  if ($answer -match '^(y|yes)$') {
    foreach ($file in Get-Content $listing) { Remove-Item (Join-Path $game $file) -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $game 'MelonLoader') -Recurse -Force -ErrorAction SilentlyContinue   # incl. files it generated on first start
    Remove-Item $listing -Force
    Say 'MelonLoader removed (your Mods and UserData folders were kept).' 'Green'
  }
}
Say 'Done. (Steam > Verify integrity of game files also restores everything.)' 'Cyan'
