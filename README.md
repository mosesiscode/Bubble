# Bubble

A lightweight desktop music player with a dark, bouncy UI. Built with Python and PySide6.

## Features
- Play your local music (MP3, FLAC, M4A, OGG, WAV and more) with covers read from the file tags
- Synced lyrics from LRCLIB or a `.lrc` file, or write/import your own, with a fullscreen lyrics mode
- Import links from YouTube, YouTube Music and SoundCloud (streams through yt-dlp)
- One place to import playlists from Spotify (spotDL download), YouTube, YouTube Music, SoundCloud, and public Deezer; playlist names are carried into Bubble playlists
- Remove unwanted saved SoundCloud stream playlists from the library without deleting audio files
- Download Spotify tracks, albums, and playlists with spotDL, including embedded tags and cover art
- Spotify playlist downloads enter the library as each track completes, with elapsed-time progress, pause/resume, cancellation, and retry after partial or failed downloads
- Create and manage persistent playlists, add selected library tracks, and play through a drag-reorderable queue
- Live audio spectrum visualizer and an audio-reactive progress scrubber when the installed Qt backend provides decoded audio buffers; compact layout for narrower windows
- Local Albums and Artists views, dated play history, ratings, smart playlists, M3U import/export, metadata filters, bulk tag editing, content-hash duplicate checks, and library repair tools
- Track editing that renders a separate trimmed/effected copy, with a 10-band equalizer, reverb, distortion, speed, and pitch controls
- Quick bass/mid/treble EQ presets in the audio editor
- Optional Discord Rich Presence, trusted local track-action plugins, mini-player, sleep timer, configurable shortcuts, and audio output selection
- Dark and light app themes, custom accent, dominant-color extraction from artwork, layout presets, opacity, high-contrast and keyboard-accessible controls, QSS styling, and sidebar section controls
- No analytics or telemetry collection. Bubble contacts music providers for media you play or import and requested cover art or lyrics; Discord reporting is opt-in.
- Synced lyrics can be saved beside downloaded tracks as `.lrc` files
- Apple Music library import (songs saved as files only)
- Liked songs, recently played, background colour choices, and your own animated background (GIF, WebP, MP4, WebM or image)
- Optional Genius lyrics (add your own free API token in Settings)

## Run
```
pip install -r requirements.txt
python app.py
```

## Project layout
- `app.py` is the stable launcher used for direct runs and packaged builds.
- `src/bubble/application.py` contains the desktop window and app startup.
- `src/bubble/config.py` owns AppData paths, settings persistence, and shortcut setup.
- `src/bubble/services/` contains local library metadata and music-provider import helpers.
- `assets/` contains app images and icons; `build_hooks/` contains PyInstaller collection hooks.
- `build.bat` and `build.sh` create platform builds; `scripts/versioning.py` tracks build versions.

## Build
Run `build.bat` (Windows) or `./build.sh`. Each successful build increments the patch version, starting at `1.0.1`, and saves the last built version in `last-built-version.txt`. Artifacts use `bubble-<version>-<platform>-<architecture>` naming, such as `bubble-1.0.1-win-x64.exe`. On Windows, install Inno Setup and run `build.bat` to also produce `bubble-<version>-win-x64-setup.exe`, which installs Bubble under the current user's Local AppData and creates Start Menu and optional desktop shortcuts.

## First launch
Bubble creates `%AppData%\Bubble\songs` and `%AppData%\Bubble\data` when it starts. The setup package creates Start Menu and optional desktop shortcuts, and keeps the AppData folders when Bubble is uninstalled so your music and settings remain available if you reinstall.

## Notes
- Spotify downloads use spotDL and are saved under `%AppData%\\Bubble\\songs`.
- Apple Music currently imports local tracks and playlists from an exported Music library file; public Apple Music playlist URL migration is not supported.
- Streaming from YouTube/SoundCloud may be against those services' terms. Use it at your own risk.
- Music services control their own advertisements, accounts, catalog access, and stream quality. Bubble does not remove service ads or bypass sign-in or access controls; local playback is offline and supports formats exposed by the installed Qt media backend.
- Audio editor effects are rendered into a new file. The player currently offers playback-rate control, but its equalizer, pitch, reverb, and distortion controls are not real-time playback DSP.
- Genius lyrics use the `lyricsgenius` package, which reads Genius web pages. Genius does not officially allow this, so use it at your own risk.
- Not affiliated with Spotify, YouTube, SoundCloud or Apple. Their names and logos belong to their owners.
- Settings and spotDL cache data are saved under `%AppData%\\Bubble\\data`.
