@echo off
REM Godotsmith IDE — Start server and open browser
REM Double-click this file to launch the IDE

echo.
echo   ==============================
echo    Godotsmith IDE
echo   ==============================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Start the server
echo Starting server on http://localhost:7777 ...
echo.

REM Open browser after a short delay
start "" /B cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:7777"

REM Run the server (blocks until Ctrl+C)
cd /d "%~dp0"
python server/app.py

echo.
echo Server stopped.
pause
