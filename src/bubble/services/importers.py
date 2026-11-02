"""Music provider import and media resolution services."""

import base64
import hashlib
import json
import os
import plistlib
import secrets
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

from http.server import BaseHTTPRequestHandler, HTTPServer

from bubble.config import UA


def fetch(url, data=None, hdr=None, raw=False):
    try: r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers={**UA, **(hdr or {})}), timeout=15).read()
    except urllib.error.HTTPError as e:
        try: m = json.loads(e.read()).get('error', ''); m = m.get('message', '') if isinstance(m, dict) else m
        except Exception: m = ''
        raise RuntimeError(f'Spotify/server said {e.code}: {m or e.reason}')
    return r if raw else json.loads(r)

def spotdl_command(args):
    cli = shutil.which('spotdl')
    if cli: return [cli, *args]
    if getattr(sys, 'frozen', False): return [sys.executable, '--spotdl-worker', *args]
    return [sys.executable, '-m', 'spotdl', *args]

def yt_import(url, src):
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': 'in_playlist', 'skip_download': True}) as y: info = y.extract_info(url, download=False)
    es = info.get('entries'); out = []
    for e in (es or [info]):
        if not e: continue
        if es and (not e.get('uploader') and not e.get('channel') or not e.get('duration')):
            vid = e.get('webpage_url') or e.get('url')
            if vid:
                if not str(vid).startswith('http'): vid = 'https://www.youtube.com/watch?v=' + str(vid)
                try:
                    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True, 'skip_download': True}) as y: e = y.extract_info(vid, download=False) or e
                except Exception: pass
        u = e.get('webpage_url') or e.get('url') or ''
        if u and not u.startswith('http'): u = 'https://www.youtube.com/watch?v=' + u
        th = e.get('thumbnail') or ((e.get('thumbnails') or [{}])[-1].get('url') or '')
        release = str(e.get('release_year') or e.get('release_date') or e.get('upload_date') or '')
        year = release[:4] if release[:4].isdigit() else ''
        out.append(dict(title=e.get('title') or 'Unknown', artist=e.get('uploader') or e.get('channel') or info.get('uploader') or '', album=e.get('album') or e.get('release_title') or ((info.get('title') or '') if es else ''),
                        year=year, dur=int((e.get('duration') or 0) * 1000), path='', url=u, src=src, cover_url=th, imported_playlist=(info.get('title') or '') if es else ''))
    if src == 'SoundCloud' and out:
        try:
            u0 = (es or [info])[0].get('webpage_url') or out[0]['url']
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': 'in_playlist', 'skip_download': True}) as y: ri = y.extract_info(u0.rstrip('/') + '/recommended', download=False)
            for e in (ri.get('entries') or [])[:12]:
                if e: out.append(dict(title=e.get('title') or 'Unknown', artist=e.get('uploader') or '', album='', dur=int((e.get('duration') or 0) * 1000), path='', url=e.get('webpage_url') or e.get('url') or '', src=src, cover_url=e.get('thumbnail') or '', rec='rec'))
        except Exception: pass
    return out

def resolve(t):
    import yt_dlp
    if t.get('src') == 'Deezer':
        q = f"ytsearch1:{t.get('artist', '')} - {t.get('title', '')} official audio"
    else:
        q = t['url'] or f"ytsearch1:{t['artist']} - {t['title']}"
    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True, 'format': 'bestaudio/best'}) as y: i = y.extract_info(q, download=False)
    if 'entries' in i: i = i['entries'][0]
    img = t.get('cover_url') or i.get('thumbnail'); data = None
    try: data = fetch(img, raw=True) if img else None
    except Exception: pass
    return i['url'], data


def deezer_import(url):
    """Import public Deezer playlist metadata; playback resolves tracks through yt-dlp search."""
    import re
    match = re.search(r'deezer\.com/(?:[a-z]{2}/)?playlist/(\d+)', url, re.I)
    if not match:
        raise ValueError('Paste a public Deezer playlist URL.')
    playlist_id = match.group(1)
    info = fetch(f'https://api.deezer.com/playlist/{playlist_id}')
    if info.get('error'):
        raise RuntimeError(info['error'].get('message', 'Deezer could not return that playlist'))
    entries = []; page = info.get('tracks', {})
    while page and len(entries) < 2000:
        entries.extend(page.get('data', []))
        next_url = page.get('next')
        if not next_url: break
        page = fetch(next_url)
    output = []
    for item in entries[:2000]:
        if not item or item.get('error'): continue
        artist = item.get('artist') or {}; album = item.get('album') or {}
        track_id = item.get('id')
        release = str(album.get('release_date') or ''); year = release[:4] if release[:4].isdigit() else ''
        output.append(dict(title=item.get('title') or 'Unknown', artist=artist.get('name') or 'Unknown artist', album=album.get('title') or info.get('title', ''), year=year, dur=int(item.get('duration') or 0) * 1000, path='', url=f'https://www.deezer.com/track/{track_id}' if track_id else '', src='Deezer', cover_url=album.get('cover_medium') or album.get('cover') or '', imported_playlist=info.get('title') or 'Deezer playlist'))
    if not output: raise RuntimeError('The Deezer playlist did not contain any accessible tracks.')
    return output

def spotify_files(paths):
    """Import from the files in Spotify's 'Download your data' export - works without Premium or the Web API."""
    mk = lambda t, a, al, tag='': dict(title=t, artist=a or 'Unknown artist', album=al or '', dur=0, path='', url='', src='Spotify', cover_url='', **({'rec': tag} if tag else {}))
    lib, cnt = [], {}
    for p in paths:
        d = json.load(open(p, encoding='utf-8-sig'))
        if isinstance(d, dict) and 'tracks' in d:                      # YourLibrary.json (saved songs)
            lib += [mk(x['track'], x.get('artist'), x.get('album')) for x in d['tracks'] if x.get('track')]
        elif isinstance(d, dict) and 'playlists' in d:                 # Playlist1.json
            for pl in d['playlists']:
                for it in pl.get('items', []):
                    t = it.get('track') or {}
                    if t.get('trackName'):
                        track = mk(t['trackName'], t.get('artistName'), t.get('albumName')); track['imported_playlist'] = pl.get('playlistName') or pl.get('name') or 'Spotify playlist'; lib.append(track)
        elif isinstance(d, list):                                      # StreamingHistory*.json -> most played
            for x in d:
                n = x.get('trackName') or x.get('master_metadata_track_name'); a = x.get('artistName') or x.get('master_metadata_album_artist_name') or ''
                if n: cnt[(n, a)] = cnt.get((n, a), 0) + 1
    return lib + [mk(n, a, '', 'top') for (n, a), c in sorted(cnt.items(), key=lambda kv: -kv[1])[:30]]

def apple_import(path):
    data = plistlib.load(open(path, 'rb')); track_table = data.get('Tracks', {}); out = []; by_id = {}
    for track_id, tr in track_table.items():
        loc = tr.get('Location')
        if not loc: continue
        p = urllib.parse.unquote(urllib.parse.urlparse(loc).path)
        if os.name == 'nt' and p[:1] == '/': p = p[1:]
        if os.path.exists(p):
            item = dict(title=tr.get('Name', ''), artist=tr.get('Artist', 'Unknown artist'), album=tr.get('Album', ''), year=str(tr.get('Year') or ''), dur=int(tr.get('Total Time', 0)), path=p, url='', src='Apple Music', cover_url='')
            out.append(item); by_id[str(track_id)] = item
    for playlist in data.get('Playlists', []):
        name = playlist.get('Name')
        if not name: continue
        for entry in playlist.get('Playlist Items', []):
            track = by_id.get(str(entry.get('Track ID')))
            if track: track.setdefault('imported_playlists', []).append(name)
    return out
