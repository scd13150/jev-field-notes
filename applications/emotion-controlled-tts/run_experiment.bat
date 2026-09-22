@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=D:\42427\TTS\index-tts\.venv\Scripts\python.exe"

echo ======================================================================
echo   Running Jev vs No-Emotion A/B Comparison Experiment
echo ======================================================================

"%PYTHON_EXE%" "%SCRIPT_DIR%run_experiment.py" %*

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Experiment execution failed with code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

echo [SUCCESS] All A/B comparison audio files regenerated successfully.
pause
