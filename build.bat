@echo off
REM Ensure we are running in the script's directory
cd /d "%~dp0"

echo Checking for virtual environment...

REM Try to activate 'venv' or '.venv'
if exist "venv\Scripts\activate.bat" (
    echo Activating 'venv'...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo Activating '.venv'...
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: No virtual environment found.
    echo Attempting to build using global system Python...
)

echo.
echo Ensuring PyInstaller is installed...
python -m pip install pyinstaller

echo.
echo Building PokeBinder...
REM Using 'python -m PyInstaller' prevents path issues
python -m PyInstaller --noconsole --onefile --name "PokeBinder" --icon=app.ico --add-data "app.ico;." tcgapp.py

echo.
if %ERRORLEVEL% EQU 0 (
    echo ---------------------------------------
    echo Build SUCCESSFUL! 
    echo Executable is located in the 'dist' folder.
    echo ---------------------------------------
) else (
    echo ---------------------------------------
    echo Build FAILED. See errors above.
    echo ---------------------------------------
)
pause