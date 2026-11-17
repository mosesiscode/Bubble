#!/bin/sh
set -e

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller
python3 -m pip install -r requirements.txt

APP_VERSION="$(python3 scripts/versioning.py next)"
BUILD_TARGET="$(python3 scripts/versioning.py target)"

python3 -m PyInstaller --noconsole --onefile --name "bubble-$APP_VERSION-$BUILD_TARGET" --paths src --add-data "assets:assets" --additional-hooks-dir build_hooks --collect-all yt_dlp --collect-all spotdl --collect-all pykakasi --collect-all ytmusicapi --collect-all imageio_ffmpeg --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets app.py

python3 scripts/versioning.py record "$APP_VERSION"
echo "Built bubble-$APP_VERSION-$BUILD_TARGET. See dist/"
