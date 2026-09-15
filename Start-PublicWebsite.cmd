@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\public-website.ps1" -Action Start
pause
