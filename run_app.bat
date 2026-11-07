@echo off
title Tro Ly AI Cham Thi Tin Hoc THPT
cd /d "%~dp0"
echo ===================================================
echo   DANG KHOI DONG TRO LY AI CHAM THI TIN HOC THPT
echo   Truy cap trinh duyet tai: http://localhost:8501
echo ===================================================
".venv\Scripts\streamlit.exe" run app.py
pause

