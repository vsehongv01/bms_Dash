@echo off
title [BMS] Integrated System
echo Starting Integrated Management System...

:: 1. 브라우저 경로 고정
set PLAYWRIGHT_BROWSERS_PATH=%~dp0pw-browsers

:: 2. 메인 페이지(app.py)만 실행
:: app.py가 실행되면서 내부의 navigation 설정에 따라 다른 파일들을 불러옵니다.
"%~dp0venv\Scripts\python.exe" -m streamlit run app.py

pause