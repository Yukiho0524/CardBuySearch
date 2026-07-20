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

rem ---- 清理殘留的舊伺服器（Windows 允許多程序綁同一埠，殘骸會搶走請求）----
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    tasklist /fi "PID eq %%p" 2>nul | findstr /i "python" >nul && (
        echo 關閉殘留的舊網站程序 PID %%p
        taskkill /PID %%p /F >nul 2>&1
    )
)

rem ---- 檢查資料庫 ----
if not exist "data\cards.db" (
    echo [!] 尚未建立卡牌資料庫，請先依 README 跑爬蟲建庫
)

rem ---- 開放防火牆（讓同內網的人能連，需系統管理員；失敗不影響本機使用）----
netsh advfirewall firewall show rule name="CardBuySearch" >nul 2>&1 || (
    netsh advfirewall firewall add rule name="CardBuySearch" dir=in action=allow ^
        protocol=TCP localport=5000 >nul 2>&1 ^
        && echo 已開放防火牆連接埠 5000 ^
        || echo [!] 無法自動開放防火牆（需以系統管理員身分執行）。同事若連不上，請對此 bat 按右鍵「以系統管理員身分執行」一次。
)

rem ---- 找出本機內網 IP，顯示給同事連 ----
set "LANIP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined LANIP set "LANIP=%%a"
)
set "LANIP=%LANIP: =%"

rem ---- 啟動網站並開啟瀏覽器 ----
echo ============================================================
echo  CardBuySearch 已啟動（關閉此視窗即停止網站）
echo  本機開啟：http://localhost:5000
if defined LANIP echo  同內網的人開啟：http://%LANIP%:5000
echo ============================================================
start "" "http://localhost:5000"
python app.py
pause
