@echo off
REM PR-DASHBOARD-v0 launcher (Windows).
REM Opens the dashboard at http://localhost:8501.
cd /d "%~dp0\.."
streamlit run dashboard\v0_main.py --server.port 8501 --server.headless true
