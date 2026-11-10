@echo off
chcp 65001 >nul
title Shopee Poster Studio - Quick Setup & Launcher
echo ============================================================
echo   Shopee Video Poster Pro - Setup & Launcher
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] ตรวจสอบ Python ในเครื่อง...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] ไม่พบ Python ในระบบ!
    echo กรุณาติดตั้ง Python 3.10 หรือ 3.11 และอย่าลืมติ๊ก "Add Python to PATH" ตอนติดตั้ง
    echo.
    pause
    exit /b 1
)

echo [2/3] กำลังติดตั้ง / ตรวจสอบ Python Packages ที่จำเป็น...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] การติดตั้งแพ็กเกจบางตัวอาจติดขัด กำลังลองติดตั้งตัวหลัก...
    python -m pip install requests pillow curl_cffi beautifulsoup4 pywebview
)

echo.
echo [3/3] กำลังสร้าง Shortcut บนหน้าจอ Desktop...
cscript //nologo create_shortcut.vbs

echo.
echo ============================================================
echo   พร้อมเปิดใช้งาน Shopee Poster Studio!
echo   กำลังเปิดเบราว์เซอร์ http://localhost:8090
echo ============================================================
echo.

start "" "http://localhost:8090"
python shopee_web_server.py

pause

