@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py desktop.py) else (python desktop.py)
if errorlevel 1 pause
