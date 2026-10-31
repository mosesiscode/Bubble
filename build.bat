@echo off
pip install -r requirements.txt
pyinstaller --noconsole --onefile --name BubblePlayer --icon assets\logo.ico --add-data "assets;assets" --collect-all yt_dlp app.py
echo.
echo Done. Your app is dist\BubblePlayer.exe
pause
