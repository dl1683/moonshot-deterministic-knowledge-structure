@echo off
setlocal

python -m pytest -q
if errorlevel 1 exit /b %errorlevel%

python tools/function_smoke.py
if errorlevel 1 exit /b %errorlevel%

exit /b 0
