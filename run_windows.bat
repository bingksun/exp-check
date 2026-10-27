@echo off
rem Double-click this file to start exp-check. Keep this window open while you use the app.
cd /d "%~dp0"
python -m streamlit run app.py
pause
