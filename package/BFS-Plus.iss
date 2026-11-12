; BFS Plus setup wizard (Inno Setup 6). Built by build_package.py into dist/public/BFS-Plus-<version>-Setup.exe
; Installs the same files as "Install BFS Plus.bat" (public build: no game files are shipped).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\dist\public\BFS-Plus-" + AppVersion
#endif

[Setup]
AppId={{7E3C2B9A-5F41-4C8E-9B6D-2A1F0E8C4D73}
AppName=BFS Plus
AppVersion={#AppVersion}
AppVerName=BFS Plus {#AppVersion}
AppPublisher=BFS Plus community mod
AppPublisherURL=https://github.com/Tann2019/bfs-plus
AppSupportURL=https://github.com/Tann2019/bfs-plus/issues
WizardStyle=modern
WizardSizePercent=100
DefaultDirName={code:DefaultGameDir}
AppendDefaultDirName=no
DirExistsWarning=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallFilesDir={app}\UserData\BfsPlus
UninstallDisplayName=BFS Plus (Beat For Speed mod)
OutputDir=..\dist\public
OutputBaseFilename=BFS-Plus-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes

[Messages]
SelectDirDesc=Where is Beat For Speed installed?
SelectDirLabel3=Setup found this Beat For Speed folder through Steam. If it is wrong, choose the folder that contains beatforspeed.exe.
SelectDirBrowseLabel=To continue, click Next.

[Tasks]
Name: "melonloader"; Description: "Download and install MelonLoader 0.7.3 (needed for the 3D lyrics in game, ~30 MB from github.com/LavaGang)"; Check: not MelonLoaderInstalled

[Files]
Source: "{#StageDir}\game-mod\BfsLyric3D.dll"; DestDir: "{app}\Mods"; Flags: ignoreversion
Source: "{#StageDir}\editor\accessibility.js"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\editor\editor_plus.css"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\editor\editor_plus_i18n.js"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\editor\lyric_tap_sync.js"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\editor\lyric3d_store.js"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\editor\lyric_designer.js"; DestDir: "{app}\Tools\chart_editor"; Flags: ignoreversion
Source: "{#StageDir}\README.txt"; DestDir: "{app}\UserData\BfsPlus"; DestName: "BFS Plus README.txt"; Flags: ignoreversion isreadme

[Code]
const
  MelonLoaderUrl = 'https://github.com/LavaGang/MelonLoader/releases/download/v0.7.3/MelonLoader.x64.zip';
  BackupFolder = 'Tools\chart_editor\_bfs_plus_backup';
  CacheTag = 'bfsplus-{#AppVersion}';

var
  DownloadPage: TDownloadWizardPage;

{ ---------------------------------------------------------------- finding the game }

function IsGameFolder(Folder: String): Boolean;
begin
  Result := FileExists(AddBackslash(Folder) + 'beatforspeed.exe');
end;

function DefaultGameDir(Param: String): String;
var
  SteamPath, Line, Candidate: String;
  Lines: TArrayOfString;
  Index, Quote: Integer;
begin
  Result := ExpandConstant('{commonpf32}\Steam\steamapps\common\Beat For Speed');
  if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', SteamPath) then
    if not RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath', SteamPath) then
      Exit;
  StringChangeEx(SteamPath, '/', '\', True);
  Candidate := AddBackslash(SteamPath) + 'steamapps\common\Beat For Speed';
  if IsGameFolder(Candidate) then begin Result := Candidate; Exit; end;
  { other Steam library folders are listed in libraryfolders.vdf as   "path"   "D:\\SteamLibrary" }
  if LoadStringsFromFile(AddBackslash(SteamPath) + 'steamapps\libraryfolders.vdf', Lines) then
    for Index := 0 to GetArrayLength(Lines) - 1 do
    begin
      Line := Trim(Lines[Index]);
      if Pos('"path"', Line) = 1 then
      begin
        Line := Trim(Copy(Line, 7, Length(Line)));
        Quote := Pos('"', Line);
        if Quote = 1 then
        begin
          Line := Copy(Line, 2, Length(Line));
          Line := Copy(Line, 1, Pos('"', Line) - 1);
          StringChangeEx(Line, '\\', '\', True);
          Candidate := AddBackslash(Line) + 'steamapps\common\Beat For Speed';
          if IsGameFolder(Candidate) then begin Result := Candidate; Exit; end;
        end;
      end;
    end;
end;

function MelonLoaderInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\MelonLoader\net6\MelonLoader.dll'));
end;

function GameIsRunning: Boolean;
var
  Locator, Service, Found: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Found := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''beatforspeed.exe''');
    Result := Found.Count > 0;
  except
  end;
end;

{ ---------------------------------------------------------------- wizard pages }

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading MelonLoader', 'The mod loader the 3D lyrics need. This only happens once.', @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if not IsGameFolder(WizardDirValue) then
    begin
      MsgBox('That folder does not contain beatforspeed.exe.' + #13#10#13#10 +
             'In Steam: right-click Beat For Speed > Manage > Browse local files, and use that folder.', mbError, MB_OK);
      Result := False;
    end
    else if not FileExists(AddBackslash(WizardDirValue) + 'Tools\chart_editor\chart_editor.html') then
    begin
      MsgBox('The chart editor was not found in this folder (Tools\chart_editor). Verify the game files in Steam and try again.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = wpReady then
  begin
    while GameIsRunning do
      if MsgBox('Beat For Speed is running. Please close it, then click OK.', mbInformation, MB_OKCANCEL) = IDCANCEL then
      begin
        Result := False;
        Exit;
      end;
    if WizardIsTaskSelected('melonloader') then
    begin
      DownloadPage.Clear;
      DownloadPage.Add(MelonLoaderUrl, 'MelonLoader.x64.zip', '');
      DownloadPage.Show;
      try
        try
          DownloadPage.Download;
        except
          if MsgBox('MelonLoader could not be downloaded:' + #13#10 + GetExceptionMessage + #13#10#13#10 +
                    'Continue without it? (The editor upgrades still install; 3D lyrics in game need MelonLoader.)',
                    mbConfirmation, MB_YESNO) = IDNO then
            Result := False;
        end;
      finally
        DownloadPage.Hide;
      end;
    end;
  end;
end;

{ ---------------------------------------------------------------- editor page hooks }

function IsModdedPage(const Text: AnsiString): Boolean;
begin
  Result := (Pos('BFS Plus', Text) > 0) or (Pos('editor_plus', Text) > 0);
end;

{ insert Addition right after the end of the line that contains Marker }
function InsertAfterLine(var Text: AnsiString; const Marker, Addition: String): Boolean;
var
  At, LineEnd: Integer;
begin
  Result := False;
  At := Pos(Marker, Text);
  if At = 0 then Exit;
  LineEnd := At;
  while (LineEnd <= Length(Text)) and (Text[LineEnd] <> #10) do LineEnd := LineEnd + 1;
  Insert(Addition + #10, Text, LineEnd + 1);
  Result := True;
end;

function LastPos(const Needle: String; const Text: AnsiString): Integer;
var
  Start, Found: Integer;
  Rest: AnsiString;
begin
  Result := 0;
  Start := 1;
  Rest := Text;
  Found := Pos(Needle, Rest);
  while Found > 0 do
  begin
    Result := Start + Found - 1;
    Start := Result + 1;
    Rest := Copy(Text, Start, Length(Text));
    Found := Pos(Needle, Rest);
  end;
end;

procedure HookEditorPage;
var
  Folder, Stock, Page: String;
  Text: AnsiString;
  At: Integer;
begin
  Folder := ExpandConstant('{app}\Tools\chart_editor');
  Stock := ExpandConstant('{app}\' + BackupFolder + '\chart_editor.html');
  Page := AddBackslash(Folder) + 'chart_editor.html';
  if not LoadStringFromFile(Stock, Text) then Exit;
  At := Pos('</head>', Text);
  if At > 0 then Insert('<link rel="stylesheet" href="editor_plus.css?v=' + CacheTag + '"><!-- BFS Plus -->' + #10, Text, At);
  InsertAfterLine(Text, '<script src="locales.js', '<script src="editor_plus_i18n.js?v=' + CacheTag + '"></script><!-- BFS Plus -->');
  InsertAfterLine(Text, '<script src="lyrics.js', '<script src="lyric3d_store.js?v=' + CacheTag + '"></script><!-- BFS Plus -->');
  At := LastPos('</body>', Text);
  if At > 0 then
    Insert('<!-- BFS Plus -->' + #10 +
           '<script src="accessibility.js?v=' + CacheTag + '"></script>' + #10 +
           '<script src="lyric_tap_sync.js?v=' + CacheTag + '"></script>' + #10 +
           '<script src="lyric_designer.js?v=' + CacheTag + '"></script>' + #10, Text, At);
  { optional larger text (Settings > Accessibility), read by the editor's own zoom code }
  if Pos('function updateEditorViewport(){', Text) > 0 then
    InsertAfterLine(Text, 'editorScale = 1;',
      '  try { const saved = Number(localStorage.getItem(''chart_editor_ui_scale'')); if(localStorage.getItem(''chart_editor_a11y'') === ''true'' && saved >= 1 && saved <= 2) editorScale = saved; } catch {} // BFS Plus');
  SaveStringToFile(Page, Text, False);
end;

procedure BackUpEditorPage;
var
  Page, Backup: String;
  Text: AnsiString;
begin
  Page := ExpandConstant('{app}\Tools\chart_editor\chart_editor.html');
  Backup := ExpandConstant('{app}\' + BackupFolder);
  ForceDirectories(Backup);
  { only the game's own page is backed up, so a game update's new page replaces an older backup }
  if LoadStringFromFile(Page, Text) and not IsModdedPage(Text) then
    FileCopy(Page, AddBackslash(Backup) + 'chart_editor.html', False);
end;

{ ---------------------------------------------------------------- MelonLoader }

procedure InstallMelonLoader;
var
  Zip: String;
  Shell, Source, Target: Variant;
  Waited: Integer;
begin
  Zip := ExpandConstant('{tmp}\MelonLoader.x64.zip');
  if not FileExists(Zip) then Exit;
  WizardForm.StatusLabel.Caption := 'Installing MelonLoader...';
  Shell := CreateOleObject('Shell.Application');
  Source := Shell.NameSpace(Zip);
  Target := Shell.NameSpace(ExpandConstant('{app}'));
  { 4 = no progress dialog, 16 = yes to all, 1024 = no error UI }
  Target.CopyHere(Source.Items, 4 + 16 + 1024);
  Waited := 0;
  while (not MelonLoaderInstalled) and (Waited < 120) do
  begin
    Sleep(500);
    Waited := Waited + 1;
  end;
  if not MelonLoaderInstalled then
    MsgBox('MelonLoader could not be unpacked into the game folder. You can install it by hand from github.com/LavaGang/MelonLoader (v0.7.3).', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    BackUpEditorPage
  else if CurStep = ssPostInstall then
  begin
    HookEditorPage;
    if WizardIsTaskSelected('melonloader') then InstallMelonLoader;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption := 'BFS Plus is installed.' + #13#10#13#10 +
      'Start Beat For Speed: songs with lyrics now show them as 3D signs beside the road. ' +
      'In the chart editor (Ctrl+F5 if it was open) you will find the new "3D Lyrics" button.' + #13#10#13#10 +
      'The first start after installing MelonLoader takes a few extra minutes.';
end;

{ ---------------------------------------------------------------- uninstall: put the game's editor page back }

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Backup: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Backup := ExpandConstant('{app}\' + BackupFolder + '\chart_editor.html');
    if FileExists(Backup) then
    begin
      FileCopy(Backup, ExpandConstant('{app}\Tools\chart_editor\chart_editor.html'), False);
      DeleteFile(Backup);
    end;
    { the folder may also hold backups made by the script installer: remove it only when empty }
    RemoveDir(ExpandConstant('{app}\' + BackupFolder));
  end;
end;
