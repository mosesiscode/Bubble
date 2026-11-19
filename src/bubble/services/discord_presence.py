"""Opt-in Discord Rich Presence bridge. No connection is made unless enabled."""

import json
import queue
import re
import threading
import time
import urllib.parse
import urllib.request

try:
    from pypresence import Presence
except Exception:
    Presence = None

DEFAULT_DISCORD_ID = '1566943790499889264'


class DiscordPresence:
    def __init__(self, client_id=DEFAULT_DISCORD_ID):
        self.client_id = str(client_id or DEFAULT_DISCORD_ID).strip()
        self.events = queue.Queue(maxsize=1)
        self._art_cache = {}
        self.thread = threading.Thread(target=self._run, daemon=True, name='BubbleDiscordPresence')
        self.thread.start()

    def update(self, title, artist, playing, position_ms=0, duration_ms=0, cover_url=''):
        event = (
            str(title or 'Music'),
            str(artist or 'Bubble Player'),
            bool(playing),
            int(position_ms),
            int(duration_ms),
            str(cover_url or '').strip(),
        )
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass
        try:
            self.events.put_nowait(event)
        except queue.Full:
            pass

    def stop(self):
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass
        try:
            self.events.put_nowait(None)
        except queue.Full:
            pass

    def _get(self, url, timeout=4):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BubblePlayer/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', 'ignore')

    def _find_cover(self, title, artist, cover_url):
        if cover_url.startswith(('http://', 'https://')):
            return cover_url
        cache_key = (title.casefold(), artist.casefold())
        if cache_key in self._art_cache:
            return self._art_cache[cache_key]

        clean_artist = '' if artist.startswith('Unknown') else artist
        term = f'{clean_artist} {title}'.strip()
        found = ''

        # 1. iTunes Search API
        try:
            url = 'https://apple.com?' + urllib.parse.urlencode({'term': term, 'media': 'music', 'limit': 1})
            data = json.loads(self._get(url))
            results = data.get('results') or []
            if results and isinstance(results[0], dict) and results[0].get('artworkUrl100'):
                found = results[0]['artworkUrl100'].replace('100x100bb', '512x512bb')
        except Exception:
            pass

        # 2. Deezer Public Search API (great for indie & SoundCloud-to-DSP uploads)
        if not found:
            try:
                url = 'https://deezer.com?' + urllib.parse.urlencode({'q': term, 'limit': 1})
                data = json.loads(self._get(url))
                results = data.get('data') or []
                if results and isinstance(results[0], dict):
                    album = results[0].get('album') or {}
                    found = album.get('cover_big') or album.get('cover_medium') or ''
            except Exception:
                pass

        # 3. SoundCloud public search fallback (underground / unreleased tracks)
        if not found:
            try:
                url = 'https://soundcloud.com?' + urllib.parse.urlencode({'q': term})
                html = self._get(url, timeout=5)
                match = re.search(r'https://i1\.sndcdn\.com/artworks-[a-zA-Z0-9_-]+-(?:large|t500x500)\.(?:jpg|png)', html)
                if match:
                    found = match.group(0).replace('-large.', '-t500x500.')
            except Exception:
                pass

        if not found:
            found = 'logo'

        self._art_cache[cache_key] = found
        return found

    def _run(self):
        if not self.client_id or Presence is None:
            return
        try:
            rpc = Presence(self.client_id)
            rpc.connect()
        except Exception:
            return
        last_event = None
        last_update = 0.0
        while True:
            try:
                event = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if event is None:
                try:
                    rpc.clear()
                    rpc.close()
                except Exception:
                    pass
                return
            if event == last_event and time.monotonic() - last_update < 15:
                continue
            title, artist, playing, position, duration, cover_url = event
            try:
                image = self._find_cover(title, artist, cover_url)
                options = {
                    'details': title[:128],
                    'state': artist[:128],
                    'large_image': image,
                    'large_text': 'Bubble Player',
                }
                if image != 'logo':
                    options['small_image'] = 'logo'
                    options['small_text'] = 'Bubble'
                if playing:
                    start = int(time.time() - max(0, position) / 1000)
                    options['start'] = start
                    if duration > 0:
                        options['end'] = start + int(duration / 1000)
                rpc.update(**options)
                last_event = event
                last_update = time.monotonic()
            except Exception:
                last_event = None
