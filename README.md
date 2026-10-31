# Bubble

A lightweight desktop music player with a dark, bouncy UI. Built with Python and PySide6.

## Features
- Play your local music (MP3, FLAC, M4A, OGG, WAV and more) with covers read from the file tags
- Synced lyrics from LRCLIB or a `.lrc` file, or write/import your own, with a fullscreen lyrics mode
- Import links from YouTube, YouTube Music and SoundCloud (streams through yt-dlp)
- Import Spotify songs from your Spotify data download (no Premium needed)
- Apple Music library import (songs saved as files only)
- Liked songs, recently played, background colour choices

## Run
```
pip install -r requirements.txt
python app.py
```

## Build an exe
Run `build.bat` (Windows) or `./build.sh`. The exe appears in `dist/`.

## Notes
- Spotify "Connect" uses Spotify's Web API, which only works when the account that owns the app has Spotify Premium. Use "Import data export" otherwise.
- Streaming from YouTube/SoundCloud may be against those services' terms. Use it at your own risk.
- Not affiliated with Spotify, YouTube, SoundCloud or Apple. Their names and logos belong to their owners.
- Settings are saved in `~/.bubbleplayer.json` on your computer (never in this repo).
