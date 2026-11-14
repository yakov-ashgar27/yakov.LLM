@echo off
rem Double-click to start yakov.LLM on Windows, then open http://localhost:8000
cd /d "%~dp0"
if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
start "" http://localhost:8000
python -m yakovllm
