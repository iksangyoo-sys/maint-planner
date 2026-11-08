@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/2] 필요한 패키지 확인 중...
py -m pip install -q -r requirements.txt
echo [2/2] 프로젝트 플래너 실행: http://127.0.0.1:5000
start "" http://127.0.0.1:5000
py app.py
pause
