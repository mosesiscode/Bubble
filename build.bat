@echo off
set "PYTHON=C:\Users\jordan\AppData\Local\Python\pythoncore-3.14-64\python.exe"
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
for /f "delims=" %%v in ('"%PYTHON%" scripts\versioning.py next') do set "APP_VERSION=%%v"
for /f "delims=" %%p in ('"%PYTHON%" scripts\versioning.py target') do set "BUILD_TARGET=%%p"
if not defined APP_VERSION exit /b 1
if not defined BUILD_TARGET exit /b 1
"%PYTHON%" -m PyInstaller --noconsole --onefile --name "bubble-%APP_VERSION%-%BUILD_TARGET%" --icon assets\logo.ico --paths src --add-data "assets;assets" --additional-hooks-dir build_hooks --collect-all yt_dlp --collect-all spotdl --collect-all pykakasi --collect-all ytmusicapi --collect-all imageio_ffmpeg --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets app.py
if errorlevel 1 exit /b 1
if /I "%BUILD_TARGET%"=="win-x64" (
  where ISCC.exe >nul 2>nul
  if not errorlevel 1 (
    ISCC.exe /DMyAppVersion=%APP_VERSION% installer.iss
    if errorlevel 1 exit /b 1
  ) else (
    echo Inno Setup was not found. The portable EXE was built; install Inno Setup to also create a shortcut-enabled setup package.
  )
)
"%PYTHON%" scripts\versioning.py record %APP_VERSION%
if errorlevel 1 exit /b 1
echo.
echo Built bubble-%APP_VERSION%-%BUILD_TARGET%. Your app is in dist\.
if exist "dist\bubble-%APP_VERSION%-win-x64-setup.exe" echo Setup package: dist\bubble-%APP_VERSION%-win-x64-setup.exe
pause
