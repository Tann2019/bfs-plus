@echo off
rem Drag an audio file onto this .bat (or run: make_chart.bat "song.mp3" -d 3 --scene city)
rem Output: chart_pipeline\charts\<song name>\chart.json (notes + lyrics) + audio + report.json
rem Optional: --lyrics-text lyrics.txt   (official lyrics; only timing is computed)
if not defined BFS_PYTHON set "BFS_PYTHON=python"
"%BFS_PYTHON%" "%~dp0make_chart.py" %*
pause
