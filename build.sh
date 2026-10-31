#!/bin/sh
pip install -r requirements.txt
pyinstaller --noconsole --onefile --name BubblePlayer --add-data "assets:assets" --collect-all yt_dlp app.py
echo "Done. See dist/"
