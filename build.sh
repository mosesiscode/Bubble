#!/bin/sh
pip install -r requirements.txt
APP_VERSION="$(python scripts/versioning.py next)" || exit 1
BUILD_TARGET="$(python scripts/versioning.py target)" || exit 1
pyinstaller --noconsole --onefile --name "bubble-$APP_VERSION-$BUILD_TARGET" --paths src --add-data "assets:assets" --additional-hooks-dir build_hooks --collect-all yt_dlp --collect-all spotdl --collect-all pykakasi --collect-all ytmusicapi --collect-all imageio_ffmpeg --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets app.py || exit 1
python scripts/versioning.py record "$APP_VERSION" || exit 1
echo "Built bubble-$APP_VERSION-$BUILD_TARGET. See dist/"
