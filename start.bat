@echo off
rem switch console to UTF-8 so Chinese output and the banner render correctly
chcp 65001 >nul
rem the banner is 118 columns wide, widen the window to avoid wrapping
mode con: cols=120 lines=40 >nul 2>nul
cd /d "%~dp0"
".venv\Scripts\python.exe" run.py --pause %*
