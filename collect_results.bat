@echo off
rem Double-click to fetch finished evaluation batches from Anthropic, score them,
rem and write docs\eval.md plus the summary table in README.md.
rem Safe to run repeatedly: batches that are not finished yet are simply reported.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
python tests\run_eval.py collect
echo.
pause
