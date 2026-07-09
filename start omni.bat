@echo off
REM OmniRoute — chay thay 9router khi het quota (cung port 20128, factory khong can doi config)
REM Double-click hoac: start omni.bat

setlocal EnableExtensions
chcp 65001 >nul 2>&1
title OmniRoute — Factory AI Gateway

set "OMNIRoute_DIR=D:\OmniRoute\OmniRoute"
if defined OMNIRoute_HOME set "OMNIRoute_DIR=%OMNIRoute_HOME%"
set "PORT=20128"
set "API_URL=http://localhost:%PORT%/v1"
set "DASH_URL=http://localhost:%PORT%/"

echo.
echo ============================================================
echo   OmniRoute — thay 9router khi het quota
echo ============================================================
echo.
echo   Buoc 1: TAT 9router (dong app / tat process tren port %PORT%)
echo   Buoc 2: Script nay khoi dong OmniRoute
echo   Buoc 3: Factory giu nguyen — base_url = %API_URL%
echo.
echo   Dashboard: %DASH_URL%
echo   OmniRoute: %OMNIRoute_DIR%
echo.

if not exist "%OMNIRoute_DIR%\package.json" (
    echo [LOI] Khong tim thay OmniRoute tai:
    echo        %OMNIRoute_DIR%
    echo.
    echo Dat bien OMNIRoute_HOME neu cai o cho khac, vi du:
    echo   set OMNIRoute_HOME=D:\path\to\OmniRoute
    echo.
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Node.js. Can Node 22+ cho OmniRoute.
    pause
    exit /b 1
)

if not exist "%OMNIRoute_DIR%\.env" (
    echo [LOI] Chua co .env trong OmniRoute.
    echo        copy .env.example .env va dien JWT_SECRET, API_KEY_SECRET, INITIAL_PASSWORD
    pause
    exit /b 1
)

if not exist "%OMNIRoute_DIR%\node_modules" (
    echo [INFO] Lan dau — dang npm install (co the mat vai phut)...
    pushd "%OMNIRoute_DIR%"
    call npm install
    if errorlevel 1 (
        echo [LOI] npm install that bai.
        popd
        pause
        exit /b 1
    )
    popd
    echo.
)

netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [CANH BAO] Port %PORT% dang co process lang nghe.
    echo            Co the 9router van chay — TAT truoc khi tiep tuc.
    echo.
    choice /C YN /M "Van chay OmniRoute (Y) hay thoat de tat 9router (N)"
    if errorlevel 2 (
        echo Da huy. Tat 9router roi chay lai file nay.
        pause
        exit /b 1
    )
    echo.
)

echo [INFO] Mo dashboard trong trinh duyet...
start "" "%DASH_URL%"

echo [INFO] Dang khoi dong OmniRoute (npm run dev)...
echo        Ctrl+C de dung. Cua so nay phai mo khi factory chay.
echo.

pushd "%OMNIRoute_DIR%"
call npm run dev
set "EXIT_CODE=%ERRORLEVEL%"
popd

echo.
if not "%EXIT_CODE%"=="0" (
    echo [LOI] OmniRoute thoat voi ma %EXIT_CODE%.
) else (
    echo OmniRoute da dung.
)
pause
endlocal
exit /b %EXIT_CODE%
