# Locates the Beat For Speed install through Steam's library folders. Dot-sourced by install/uninstall.
function Find-GameDir {
  $candidates = @()
  foreach ($key in 'HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam') {
    try { $p = (Get-ItemProperty $key -ErrorAction Stop).SteamPath; if (-not $p) { $p = (Get-ItemProperty $key).InstallPath }; if ($p) { $candidates += $p } } catch {}
  }
  $libs = @()
  foreach ($steam in $candidates) {
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    $libs += $steam
    if (Test-Path $vdf) {
      foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) { $libs += $m.Groups[1].Value -replace '\\\\', '\' }
    }
  }
  foreach ($lib in ($libs | Select-Object -Unique)) {
    $dir = Join-Path $lib 'steamapps\common\Beat For Speed'
    if (Test-Path (Join-Path $dir 'Tools\chart_editor\chart_editor.html')) { return $dir }
  }
  return $null
}
