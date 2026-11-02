"""Local audio metadata and lyric-file helpers."""

import os
import unicodedata
import re
import hashlib

try:
    import mutagen
except Exception:
    mutagen = None


def tag(path):
    d = dict(title=os.path.splitext(os.path.basename(path))[0], artist='Unknown artist', album='', year='', dur=0, path=path, url='', src='Local', cover_url='')
    try:
        f = mutagen.File(path, easy=True)
        if f:
            d['dur'] = int(f.info.length * 1000); g = lambda k: (f.get(k) or [''])[0]
            d['title'] = g('title') or d['title']; d['artist'] = g('artist') or d['artist']; d['album'] = g('album')
            release = str(g('date') or g('originaldate') or g('year') or '')
            d['year'] = release[:4] if re.match(r'^\d{4}', release) else ''
            tags = getattr(f, 'tags', None) or {}
            gain = next((tags.get(k) for k in ('replaygain_track_gain', 'REPLAYGAIN_TRACK_GAIN', 'TXXX:replaygain_track_gain') if tags.get(k)), None)
            if gain:
                match = re.search(r'-?\d+(?:\.\d+)?', str(gain[0] if isinstance(gain, list) else gain))
                if match: d['gain_db'] = float(match.group())
    except Exception: pass
    return d

def extras(path):
    cov = lyr = None
    lrc = os.path.splitext(path)[0] + '.lrc'
    if os.path.exists(lrc):
        try: lyr = open(lrc, encoding='utf-8', errors='ignore').read()
        except Exception: pass
    try:
        f = mutagen.File(path); t = f.tags if f is not None else None
        if f is not None and getattr(f, 'pictures', None): cov = f.pictures[0].data
        if t is not None:
            for k in list(t.keys()):
                if cov is None and str(k).startswith('APIC'): cov = t[k].data
                if not lyr and str(k).startswith('USLT'): lyr = str(t[k].text)
            if cov is None and 'covr' in t: cov = bytes(t['covr'][0])
            if not lyr:
                v = t.get('lyrics') or t.get('\xa9lyr')
                if v: lyr = str(v[0])
    except Exception: pass
    return cov, lyr

def write_lrc(path, txt):
    if not path or not txt or not os.path.isfile(path): return
    try:
        with open(os.path.splitext(path)[0] + '.lrc', 'w', encoding='utf-8') as f: f.write(txt.strip() + '\n')
    except OSError: pass

def parse_lrc(txt):
    L = []; plain = []; has_timestamps = False; seen = set()
    metadata = re.compile(r'^(?:作曲|作词|作詞|编曲|編曲|演唱|歌手|词曲|作曲者|作词者)\s*[:：]', re.I)
    for ln in txt.splitlines():
        body = re.sub(r'\[[^\]]*\]', '', ln).strip()
        if not body or metadata.match(body): continue
        normalized = re.sub(r'\s+', ' ', body).casefold()
        stamps = re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', ln)
        if stamps:
            has_timestamps = True
            for m, sec in stamps:
                timestamp = int((int(m) * 60 + float(sec)) * 1000)
                marker = (timestamp, normalized)
                if marker not in seen: L.append((timestamp, body)); seen.add(marker)
        else:
            plain.append(body)
    if has_timestamps: L.sort(); return L, True
    plain = [re.sub(r'\s+', ' ', line).strip() for line in (plain or txt.splitlines())]
    plain = [line for line in plain if line and not metadata.match(line)]
    return [(0, line) for line in plain], False


def duplicate_groups(tracks):
    """Find tag-matched tracks and byte-identical local files without loading files into memory."""
    groups = {}
    content_by_size = {}
    def normalize(value):
        value = unicodedata.normalize('NFKD', str(value or '')).casefold()
        return ''.join(char for char in value if char.isalnum())
    for index, track in enumerate(tracks):
        title = normalize(track.get('title'))
        artist = normalize(track.get('artist'))
        if title and artist and artist not in ('unknownartist', 'unknown'):
            groups.setdefault((title, artist), []).append(index)
        path = track.get('path')
        if path and os.path.isfile(path):
            try: content_by_size.setdefault(os.path.getsize(path), []).append((index, path))
            except OSError: pass
    clusters = [set(indices) for indices in groups.values() if len(indices) > 1]
    for same_size in content_by_size.values():
        if len(same_size) < 2: continue
        by_digest = {}
        for index, path in same_size:
            try:
                digest = hashlib.sha256()
                with open(path, 'rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
                by_digest.setdefault(digest.digest(), []).append(index)
            except OSError: continue
        clusters.extend(set(indices) for indices in by_digest.values() if len(indices) > 1)
    merged = []
    for cluster in clusters:
        touching = [existing for existing in merged if existing & cluster]
        if not touching: merged.append(cluster); continue
        combined = cluster.union(*touching)
        merged = [existing for existing in merged if existing not in touching]; merged.append(combined)
    return [sorted(indices) for indices in merged if len(indices) > 1]
