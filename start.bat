@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CardBuySearch

rem ---- 檢查 Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [X] 找不到 Python，請先安裝 Python 3.10+ 並勾選加入 PATH
    pause
    exit /b 1
)

rem ---- 檢查套件，缺少才安裝 ----
echo 檢查套件中...
python -c "import flask, requests, bs4, opencc, PIL, imagehash" >nul 2>&1
if errorlevel 1 (
    echo 偵測到缺少套件，安裝中（只需第一次）...
    python -m pip install --user -r requirements.txt --disable-pip-version-check
    if errorlevel 1 (
        echo [X] 套件安裝失敗，請檢查網路後重試
        pause
        exit /b 1
    )
)

rem ---- 檢查資料庫 ----
if not exist "data\cards.db" (
    echo [!] 尚未建立卡牌資料庫，請先依 README 跑爬蟲建庫
)

rem ---- 啟動網站並開啟瀏覽器 ----
echo 啟動 CardBuySearch → http://localhost:5000 （關閉此視窗即停止網站）
start "" "http://localhost:5000"
python app.py
pause
