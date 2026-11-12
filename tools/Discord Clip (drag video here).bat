@echo off
rem Drag a recording onto this file to make a copy under Discord's 50 MB limit (boosted servers).
rem For a different size or a trimmed clip, run discord_clip.py yourself (see the top of that file).
if "%~1"=="" (
  echo Drag a video file onto this .bat to shrink it for Discord.
  pause
  exit /b
)
python "%~dp0discord_clip.py" "%~1" --crop auto
pause
