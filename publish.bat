@echo off
REM Publish godotsmith skills into a target game project directory.
REM Usage: publish.bat <target_dir> [claude_md]
REM   claude_md  Path to CLAUDE.md to use (default: CLAUDE.md from this repo)

setlocal enabledelayedexpansion

if "%~1"=="" (
    echo Usage: %0 ^<target_dir^> [claude_md]
    exit /b 1
)

set "TARGET=%~f1"
set "REPO_ROOT=%~dp0"
set "CLAUDE_MD=%~f2"
if "%CLAUDE_MD%"=="" set "CLAUDE_MD=%REPO_ROOT%game_claude.md"

echo Publishing to: %TARGET%

if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%\.claude\skills" mkdir "%TARGET%\.claude\skills"

REM Copy skills
xcopy /E /I /Y /Q "%REPO_ROOT%.claude\skills\godotsmith" "%TARGET%\.claude\skills\godotsmith" >nul
xcopy /E /I /Y /Q "%REPO_ROOT%.claude\skills\godot-task" "%TARGET%\.claude\skills\godot-task" >nul

REM Copy CLAUDE.md
copy /Y "%CLAUDE_MD%" "%TARGET%\CLAUDE.md" >nul
echo Created CLAUDE.md

REM Create .gitignore if missing
if not exist "%TARGET%\.gitignore" (
    (
        echo .claude
        echo CLAUDE.md
        echo assets
        echo screenshots
        echo .godot
        echo *.import
    ) > "%TARGET%\.gitignore"
    echo Created .gitignore
)

REM Init git if needed
if not exist "%TARGET%\.git" (
    git -C "%TARGET%" init -q 2>nul
    echo Initialized git repo
)

echo Done. Skills published to %TARGET%
