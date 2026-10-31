"""Bubble Player - Spotify-style local music player (PySide6). No HTML: compiles to an exe with PyInstaller."""
import urllib.error, queue, sys, os, re, json, base64, hashlib, secrets, threading, urllib.request, urllib.parse, plistlib, webbrowser, random, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
try: import mutagen
except Exception: mutagen = None

EXT = ('.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.wma')
CFG = os.path.join(os.path.expanduser('~'), '.bubbleplayer.json')
PH = {'K': .10, 'C': .30}          # spring stiffness / damping (calmer than before)
ACC, DIM = '#33d6e8', '#8c8c8c'
COV = {}; TH = {}                            # key -> QPixmap cache
UA = {'User-Agent': 'BubblePlayer/1.0'}

def load_cfg():
    try: return json.load(open(CFG, encoding='utf-8'))
    except Exception: return {}
def save_cfg(c):
    try: json.dump(c, open(CFG, 'w', encoding='utf-8'))
    except Exception: pass
def fmt(ms):
    s = max(0, int(ms // 1000)); return f'{s // 60}:{s % 60:02d}'
def key(t): return t['path'] or t['url'] or t['title'] + t['artist']
def gen_cover(seed, n=400):
    h = int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) % 360; pm = QPixmap(n, n); p = QPainter(pm); g = QLinearGradient(0, 0, n, n)
    g.setColorAt(0, QColor.fromHsl(h, 35, 62)); g.setColorAt(1, QColor.fromHsl((h + 40) % 360, 35, 22))
    p.fillRect(0, 0, n, n, g); p.end(); return pm

class Bridge(QObject):
    imported = Signal(list); resolved = Signal(int, str, object); lyrics = Signal(int, str); status = Signal(str); cover = Signal(str, object)

# ---------------------------------------------------------------- tags, lyrics, streaming helpers
def tag(path):
    d = dict(title=os.path.splitext(os.path.basename(path))[0], artist='Unknown artist', album='', dur=0, path=path, url='', src='Local', cover_url='')
    try:
        f = mutagen.File(path, easy=True)
        if f:
            d['dur'] = int(f.info.length * 1000); g = lambda k: (f.get(k) or [''])[0]
            d['title'] = g('title') or d['title']; d['artist'] = g('artist') or d['artist']; d['album'] = g('album')
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

def parse_lrc(txt):
    L = []
    for ln in txt.splitlines():
        body = re.sub(r'\[[^\]]*\]', '', ln).strip() or '\u266a'
        for m, sec in re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', ln): L.append((int((int(m) * 60 + float(sec)) * 1000), body))
    if L: L.sort(); return L, True
    return [(0, x) for x in txt.splitlines()], False

def fetch(url, data=None, hdr=None, raw=False):
    try: r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers={**UA, **(hdr or {})}), timeout=15).read()
    except urllib.error.HTTPError as e:
        try: m = json.loads(e.read()).get('error', ''); m = m.get('message', '') if isinstance(m, dict) else m
        except Exception: m = ''
        raise RuntimeError(f'Spotify/server said {e.code}: {m or e.reason}')
    return r if raw else json.loads(r)

def yt_import(url, src):
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': 'in_playlist', 'skip_download': True}) as y: info = y.extract_info(url, download=False)
    es = info.get('entries'); out = []
    for e in (es or [info]):
        if not e: continue
        u = e.get('webpage_url') or e.get('url') or ''
        if u and not u.startswith('http'): u = 'https://www.youtube.com/watch?v=' + u
        th = e.get('thumbnail') or ((e.get('thumbnails') or [{}])[-1].get('url') or '')
        out.append(dict(title=e.get('title') or 'Unknown', artist=e.get('uploader') or e.get('channel') or info.get('uploader') or '', album=(info.get('title') or '') if es else '',
                        dur=int((e.get('duration') or 0) * 1000), path='', url=u, src=src, cover_url=th))
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
    q = t['url'] or f"ytsearch1:{t['artist']} - {t['title']}"
    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True, 'format': 'bestaudio/best'}) as y: i = y.extract_info(q, download=False)
    if 'entries' in i: i = i['entries'][0]
    img = t.get('cover_url') or i.get('thumbnail'); data = None
    try: data = fetch(img, raw=True) if img else None
    except Exception: pass
    return i['url'], data

def spotify_liked(cid):
    ver = secrets.token_urlsafe(64)[:96]; ch = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b'=').decode()
    red = 'http://127.0.0.1:8888/callback'; got = {}
    class H(BaseHTTPRequestHandler):
        def do_GET(h):
            got['code'] = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).get('code', [''])[0]
            h.send_response(200); h.send_header('Content-Type', 'text/html'); h.end_headers(); h.wfile.write(b'<h3>Connected. You can close this tab.</h3>')
        def log_message(h, *a): pass
    srv = HTTPServer(('127.0.0.1', 8888), H); srv.timeout = 180
    webbrowser.open('https://accounts.spotify.com/authorize?' + urllib.parse.urlencode(dict(client_id=cid, response_type='code', redirect_uri=red,
                    code_challenge_method='S256', code_challenge=ch, scope='user-library-read user-top-read user-read-private')))
    for _ in range(3):
        srv.handle_request()
        if got.get('code'): break
    srv.server_close()
    if not got.get('code'): raise RuntimeError('Spotify login was not completed')
    tok = fetch('https://accounts.spotify.com/api/token', urllib.parse.urlencode(dict(grant_type='authorization_code', code=got['code'], redirect_uri=red, client_id=cid, code_verifier=ver)).encode())['access_token']
    out = []; url = 'https://api.spotify.com/v1/me/tracks?limit=50'
    while url and len(out) < 1500:
        j = fetch(url, hdr={'Authorization': 'Bearer ' + tok})
        for it in j['items']:
            t = it['track']; im = t['album']['images']
            out.append(dict(title=t['name'], artist=', '.join(a['name'] for a in t['artists']), album=t['album']['name'], dur=t['duration_ms'], path='', url='', src='Spotify', cover_url=im[0]['url'] if im else ''))
        url = j.get('next')
    B.imported.emit(out)
    mk = lambda t, tag: dict(title=t['name'], artist=', '.join(a['name'] for a in t['artists']), album=t['album']['name'], dur=t['duration_ms'], path='', url='', src='Spotify', cover_url=(t['album']['images'] or [{}])[0].get('url', ''), rec=tag)
    api = lambda u: fetch(u, hdr={'Authorization': 'Bearer ' + tok}); top = []
    try: top = api('https://api.spotify.com/v1/me/top/tracks?limit=30&time_range=medium_term')['items']; B.imported.emit([mk(t, 'top') for t in top])
    except Exception: pass
    try:
        mkt = api('https://api.spotify.com/v1/me').get('country', 'US'); have = {t['id'] for t in top}; recs = []
        for a in api('https://api.spotify.com/v1/me/top/artists?limit=6')['items']: recs += [mk(t, 'rec') for t in api(f"https://api.spotify.com/v1/artists/{a['id']}/top-tracks?market={mkt}")['tracks'][:5] if t['id'] not in have]
        B.imported.emit(recs)
    except Exception: pass
    B.status.emit(f'Spotify: {len(out)} liked songs imported'); return []

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
                    if t.get('trackName'): lib.append(mk(t['trackName'], t.get('artistName'), t.get('albumName')))
        elif isinstance(d, list):                                      # StreamingHistory*.json -> most played
            for x in d:
                n = x.get('trackName') or x.get('master_metadata_track_name'); a = x.get('artistName') or x.get('master_metadata_album_artist_name') or ''
                if n: cnt[(n, a)] = cnt.get((n, a), 0) + 1
    return lib + [mk(n, a, '', 'top') for (n, a), c in sorted(cnt.items(), key=lambda kv: -kv[1])[:30]]

def apple_import(path):
    out = []
    for tr in plistlib.load(open(path, 'rb')).get('Tracks', {}).values():
        loc = tr.get('Location')
        if not loc: continue
        p = urllib.parse.unquote(urllib.parse.urlparse(loc).path)
        if os.name == 'nt' and p[:1] == '/': p = p[1:]
        if os.path.exists(p): out.append(dict(title=tr.get('Name', ''), artist=tr.get('Artist', 'Unknown artist'), album=tr.get('Album', ''), dur=int(tr.get('Total Time', 0)), path=p, url='', src='Apple Music', cover_url=''))
    return out

def sq(o, n):
    q = o.scaled(n, n, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation); return q.copy((q.width() - n) // 2, (q.height() - n) // 2, n, n)

def lines(p, x, yc, w, a, b, ca='#fff'):
    """Two-line title/artist block, vertically centred on yc using real font metrics."""
    fa, fb = QFont('Segoe UI', 10, QFont.Bold), QFont('Segoe UI', 9); ma, mb = QFontMetrics(fa), QFontMetrics(fb); top = yc - (ma.height() + mb.height() + 2) / 2
    p.setFont(fa); p.setPen(QColor(ca)); p.drawText(QPointF(x, top + ma.ascent()), ma.elidedText(a, Qt.ElideRight, int(w)))
    p.setFont(fb); p.setPen(QColor(DIM)); p.drawText(QPointF(x, top + ma.height() + 2 + mb.ascent()), mb.elidedText(b, Qt.ElideRight, int(w)))

def glyph(kind, n, color):
    pm = QPixmap(n, n); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); ic(p, kind, QRectF(2, 2, n - 4, n - 4), QColor(color)); p.end(); return pm

def cover_worker(q):
    """Background thread: pulls (key, path, url) from the queue and emits a square cover image."""
    while True:
        k, path, url = q.get()
        try:
            data = (extras(path)[0] if mutagen else None) if path else (fetch(url, raw=True) if url else None)
            if data:
                img = QImage.fromData(data)
                if not img.isNull(): B.cover.emit(k, sq(img, 240))
        except Exception: pass

# ---------------------------------------------------------------- bouncy widgets (calmer springs)
def ic(p, k, r, col, fill=False):
    x, y, w = r.x(), r.y(), r.width(); P = lambda a, b: QPointF(x + a * w, y + b * w)
    p.setPen(QPen(col, max(1.7, w / 12), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.setBrush(Qt.NoBrush)
    def line(*pts):
        pa = QPainterPath(P(*pts[0]))
        for a in pts[1:]: pa.lineTo(P(*a))
        p.drawPath(pa)
    def tri(*pts): p.setBrush(col); p.drawPolygon(QPolygonF([P(*a) for a in pts])); p.setBrush(Qt.NoBrush)
    if k == 'play': tri((.3, .12), (.86, .5), (.3, .88))
    elif k == 'pause': line((.3, .15), (.3, .85)); line((.7, .15), (.7, .85))
    elif k == 'prev': line((.22, .2), (.22, .8)); tri((.82, .18), (.34, .5), (.82, .82))
    elif k == 'next': line((.78, .2), (.78, .8)); tri((.18, .18), (.66, .5), (.18, .82))
    elif k == 'search': p.drawEllipse(P(.44, .44), w * .26, w * .26); line((.64, .64), (.88, .88))
    elif k == 'plus': line((.5, .15), (.5, .85)); line((.15, .5), (.85, .5))
    elif k == 'back': line((.62, .15), (.28, .5), (.62, .85))
    elif k == 'fwd': line((.38, .15), (.72, .5), (.38, .85))
    elif k == 'note': line((.42, .78), (.42, .2), (.8, .12), (.8, .68)); p.drawEllipse(P(.3, .78), w * .12, w * .1); p.drawEllipse(P(.68, .68), w * .12, w * .1)
    elif k == 'heart' or k == 'heartf':
        pa = QPainterPath(P(.5, .86)); pa.cubicTo(P(.08, .6), P(.04, .22), P(.27, .2)); pa.cubicTo(P(.4, .18), P(.47, .26), P(.5, .33)); pa.cubicTo(P(.53, .26), P(.6, .18), P(.73, .2)); pa.cubicTo(P(.96, .22), P(.92, .6), P(.5, .86))
        if k == 'heartf': p.setBrush(col)
        p.drawPath(pa)
    elif k == 'folder': line((.1, .2), (.4, .2), (.5, .33), (.9, .33), (.9, .8), (.1, .8), (.1, .2))
    elif k == 'clock': p.drawEllipse(P(.5, .5), w * .38, w * .38); line((.5, .28), (.5, .5), (.66, .6))
    elif k == 'sliders': line((.25, .15), (.25, .85)); line((.5, .15), (.5, .85)); line((.75, .15), (.75, .85)); line((.15, .35), (.35, .35)); line((.4, .65), (.6, .65)); line((.65, .4), (.85, .4))
    elif k == 'close': line((.25, .25), (.75, .75)); line((.75, .25), (.25, .75))
    elif k == 'refresh': p.drawArc(QRectF(P(.18, .18), P(.82, .82)), 60 * 16, 270 * 16); line((.74, .1), (.8, .3), (.6, .32))
    elif k == 'wave': line((.2, .4), (.2, .6)); line((.35, .25), (.35, .75)); line((.5, .12), (.5, .88)); line((.65, .3), (.65, .7)); line((.8, .42), (.8, .58))
    elif k == 'playc': p.drawEllipse(P(.5, .5), w * .46, w * .46); tri((.42, .3), (.72, .5), (.42, .7))
    elif k == 'pencil': line((.18, .82), (.24, .6), (.64, .2), (.8, .36), (.4, .76), (.18, .82)); line((.55, .29), (.71, .45))
    elif k == 'import': line((.5, .12), (.5, .6)); line((.3, .42), (.5, .62), (.7, .42)); line((.18, .68), (.18, .85), (.82, .85), (.82, .68))
    elif k == 'expand': line((.15, .38), (.15, .15), (.38, .15)); line((.62, .15), (.85, .15), (.85, .38)); line((.85, .62), (.85, .85), (.62, .85)); line((.38, .85), (.15, .85), (.15, .62))
    elif k == 'dot': p.setBrush(col); p.drawEllipse(P(.5, .5), w * .17, w * .17)
    elif k == 'home': line((.1, .52), (.5, .14), (.9, .52)); line((.2, .44), (.2, .88), (.8, .88), (.8, .44))
    elif k == 'library': line((.2, .15), (.2, .85)); line((.42, .15), (.42, .85)); line((.62, .2), (.86, .82))
    elif k == 'lyrics': line((.12, .25), (.88, .25)); line((.12, .5), (.66, .5)); line((.12, .75), (.76, .75))
    elif k == 'gear':
        import math; pts = []
        for t in range(8):
            for da, rr in ((-13, .33), (-8, .45), (8, .45), (13, .33)): a = math.radians(t * 45 + da); pts.append(QPointF(x + w * (.5 + rr * math.sin(a)), y + w * (.5 - rr * math.cos(a))))
        p.drawPolygon(QPolygonF(pts)); p.drawEllipse(P(.5, .5), w * .14, w * .14)
    elif k == 'shuffle': line((.1, .3), (.3, .3), (.65, .7), (.86, .7)); line((.1, .7), (.3, .7), (.65, .3), (.86, .3)); line((.74, .2), (.87, .3), (.74, .4)); line((.74, .6), (.87, .7), (.74, .8))
    elif k == 'repeat': p.drawRoundedRect(QRectF(P(.12, .3), P(.88, .7)), w * .2, w * .2); line((.64, .14), (.8, .3), (.64, .46))
    elif k == 'vol': p.setBrush(col); p.drawPolygon(QPolygonF([P(.15, .4), P(.32, .4), P(.55, .2), P(.55, .8), P(.32, .6), P(.15, .6)])); p.setBrush(Qt.NoBrush); p.drawArc(QRectF(P(.5, .3), P(.9, .7)), -45 * 16, 90 * 16)

class Springy(QWidget):
    clicked = Signal(); grow = .08; pull = .10
    def __init__(s, pad=6):
        super().__init__(); s.setMouseTracking(True); s.pad = pad; s.st = [0., 0., 1., 0., 0., 0.]; s.hov = s.pressed = False; s.m = QPointF()
        s.tm = QTimer(s); s.tm.setInterval(16); s.tm.timeout.connect(s.step); s.setCursor(Qt.PointingHandCursor)
    def enterEvent(s, e): s.hov = True; s.tm.start()
    def leaveEvent(s, e): s.hov = s.pressed = False; s.tm.start()
    def mouseMoveEvent(s, e): s.m = e.position(); s.tm.start()
    def mousePressEvent(s, e): s.pressed = True; s.tm.start()
    def mouseReleaseEvent(s, e):
        if s.pressed and s.rect().contains(e.position().toPoint()): s.st[5] += .035; s.clicked.emit()
        s.pressed = False; s.tm.start()
    def step(s):
        st = s.st; lim = s.pad * .8
        if s.hov: tx = max(-lim, min(lim, (s.m.x() - s.width() / 2) * s.pull)); ty = max(-lim, min(lim, (s.m.y() - s.height() / 2) * s.pull)); ts = 1 + s.grow
        else: tx = ty = 0; ts = 1
        if s.pressed: ts *= .96
        K, C = PH['K'], PH['C']
        st[3] += (tx - st[0]) * K - st[3] * C; st[4] += (ty - st[1]) * K - st[4] * C; st[5] += (ts - st[2]) * K * 1.2 - st[5] * C
        st[0] += st[3]; st[1] += st[4]; st[2] += st[5]
        if max(abs(st[3]), abs(st[4]), abs(st[5] * 10)) < .01 and abs(tx - st[0]) < .05 and abs(ty - st[1]) < .05 and abs(ts - st[2]) < .001:
            st[:] = [tx, ty, ts, 0, 0, 0]; s.tm.stop()
        s.update()
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        c = s.rect().center(); p.translate(c.x() + s.st[0], c.y() + s.st[1]); p.scale(s.st[2], s.st[2]); p.translate(-c.x(), -c.y())
        s.draw(p, QRectF(s.rect()).adjusted(s.pad, s.pad, -s.pad, -s.pad))

class IconBtn(Springy):
    def __init__(s, kind, size=28, circle=False, pad=6):
        super().__init__(pad); s.kind, s.circle, s.on = kind, circle, False; s.setFixedSize(size + 2 * pad, size + 2 * pad); s.grow = .1
    def draw(s, p, r):
        if s.circle:
            bg = {'dark': QColor(0, 0, 0, 170), 'grey': QColor('#2a2a2a' if s.hov else '#1f1f1f'), 'green': QColor(ACC)}.get(s.circle, QColor('#fff')); p.setPen(Qt.NoPen); p.setBrush(bg); p.drawEllipse(r)
            ic(p, s.kind, r.adjusted(r.width() * .27, r.width() * .27, -r.width() * .27, -r.width() * .27), QColor('#fff' if s.circle in ('dark', 'grey') else '#000'))
        else:
            ic(p, s.kind, r, QColor(ACC if s.on else ('#fff' if s.hov else DIM)))
            if s.on: p.setPen(Qt.NoPen); p.setBrush(QColor(ACC)); p.drawEllipse(QPointF(r.center().x(), r.bottom() + 4), 2, 2)

class Nav(Springy):
    def __init__(s, kind, text):
        super().__init__(4); s.kind, s.text, s.on, s.cnt = kind, text, False, ''; s.setFixedHeight(42); s.grow = .03; s.pull = .05
    def draw(s, p, r):
        pass
        col = QColor('#fff' if (s.on or s.hov) else DIM); cp = r.width() < 150; ic(p, s.kind, QRectF(r.center().x() - 11 if cp else r.x() + 14, r.center().y() - 11, 22, 22), col)
        if cp: return
        p.setPen(col); f = QFont('Segoe UI', 11, QFont.Bold); p.setFont(f); p.drawText(QRectF(r.x() + 48, r.y(), r.width() - 48, r.height()), Qt.AlignVCenter | Qt.AlignLeft, s.text)
        if s.cnt: p.setPen(QColor(DIM)); p.setFont(QFont('Segoe UI', 9)); p.drawText(QRectF(r.x(), r.y(), r.width() - 14, r.height()), Qt.AlignVCenter | Qt.AlignRight, s.cnt)

class Cov(Springy):
    def __init__(s, size, radius=10, grow=.05, pad=8):
        super().__init__(pad); s.pm = None; s.rad = radius; s.grow = grow; s.setFixedSize(size + 2 * pad, size + 2 * pad); s._k = None
    def set(s, pm): s.pm = pm; s._k = None; s.update()
    def draw(s, p, r):
        if not s.pm: return
        k = (s.pm.cacheKey(), int(r.width()))
        if s._k != k: s._k = k; s._sc = s.pm.scaled(int(r.width()), int(r.width()), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        pa = QPainterPath(); pa.addRoundedRect(r, s.rad, s.rad); p.setClipPath(pa)
        p.drawPixmap(int(r.x() - (s._sc.width() - r.width()) / 2), int(r.y() - (s._sc.height() - r.height()) / 2), s._sc)

class Card(Springy):
    def __init__(s, t):
        super().__init__(6); s.t = t; s.setFixedSize(196, 258); s.grow = .02; s.pull = .04; s.pm = COV.get(key(t)) or gen_cover(t['title'] + t['artist'], 200)
    def draw(s, p, r):
        k = max(0., min(1., (s.st[2] - 1) / s.grow)) if s.hov else 0.
        p.setPen(Qt.NoPen); p.setBrush(QColor('#1f1f1f' if s.hov else '#181818')); p.drawRoundedRect(r, 8, 8)
        w = r.width() - 24; x0, y0 = r.x() + 12, r.y() + 12; pa = QPainterPath(); pa.addRoundedRect(QRectF(x0, y0, w, w), 5, 5)
        p.save(); p.setClipPath(pa); p.drawPixmap(QRectF(x0, y0, w, w), s.pm, QRectF(s.pm.rect())); p.restore()
        if k:
            p.setOpacity(k); p.setPen(Qt.NoPen); p.setBrush(QColor(ACC)); c = QRectF(x0 + w - 48, y0 + w - 48 + (1 - k) * 10, 44, 44); p.drawEllipse(c)
            ic(p, 'play', c.adjusted(13, 13, -13, -13), QColor('#000')); p.setOpacity(1)
        p.setPen(QColor('#fff')); p.setFont(QFont('Segoe UI', 10, QFont.Bold)); p.drawText(QPointF(x0, y0 + w + 24), p.fontMetrics().elidedText(s.t['title'], Qt.ElideRight, int(w)))
        p.setPen(QColor(DIM)); p.setFont(QFont('Segoe UI', 9)); p.drawText(QPointF(x0, y0 + w + 44), p.fontMetrics().elidedText(s.t['artist'], Qt.ElideRight, int(w)))

class Tile(Springy):
    def __init__(s, t):
        super().__init__(4); s.t = t; s.setFixedSize(300, 64); s.grow = .02; s.pull = .04; s.pm = COV.get(key(t)) or gen_cover(t['title'] + t['artist'], 100)
    def draw(s, p, r):
        pa = QPainterPath(); pa.addRoundedRect(r, 5, 5); p.save(); p.setClipPath(pa); p.fillRect(r, QColor(255, 255, 255, 40 if s.hov else 26))
        c = QRectF(r.x(), r.y(), r.height(), r.height()); p.drawPixmap(c, s.pm, QRectF(s.pm.rect())); p.restore()
        x = c.right() + 14; w = r.right() - x - 58; y = r.center().y()
        lines(p, x, y, w, s.t['title'], s.t['artist'])
        if s.hov: b = QRectF(r.right() - 52, y - 20, 40, 40); p.setPen(Qt.NoPen); p.setBrush(QColor(ACC)); p.drawEllipse(b); ic(p, 'play', b.adjusted(12, 12, -12, -12), QColor('#000'))

GC = {}
def dom(pm):
    c = pm.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).toImage().pixelColor(0, 0); h, sa, v, _ = c.getHsv()
    return QColor.fromHsv(max(h, 0), min(255, int(sa * 1.1) + 20), int(max(80, min(v, 210)) * .62))

class Panel(QFrame):
    """Centre panel: rounded #121212 with a gradient from the current cover's colour (full-height on the Lyrics page)."""
    def __init__(s):
        super().__init__(); s.c0 = s.c1 = QColor('#121212'); s.t = 1.; s.strong = False
        s.an = QVariantAnimation(s); s.an.setDuration(1400); s.an.setStartValue(0.); s.an.setEndValue(1.); s.an.valueChanged.connect(s._v)
    def _v(s, v): s.t = v; s.update()
    def cur(s): a, b, t = s.c0, s.c1, s.t; return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t), int(a.blue() + (b.blue() - a.blue()) * t))
    def set_col(s, c): s.c0 = s.cur(); s.c1 = c; s.an.stop(); s.an.start()
    def paintEvent(s, e):
        p = QPainter(s); pa = QPainterPath(); pa.addRoundedRect(QRectF(s.rect()), 8, 8); p.setClipPath(pa); p.fillRect(s.rect(), QColor('#121212'))
        c = s.cur(); g = QLinearGradient(0, 0, 0, s.height() if s.strong else 360); top = QColor(c); top.setAlpha(255 if s.strong else 210)
        g.setColorAt(0, top); g.setColorAt(1, QColor(c.red() // 2, c.green() // 2, c.blue() // 2) if s.strong else QColor('#121212')); p.fillRect(s.rect(), g)

class SongDelegate(QStyledItemDelegate):
    """Your Library list in the sidebar: cover, title, artist - painted by hand for speed."""
    def __init__(s, win): super().__init__(win); s.w = win; s.cur = -1
    def sizeHint(s, o, i): return QSize(0, 58)
    def paint(s, p, o, i):
        idx = i.data(Qt.UserRole); t = s.w.T[idx]; k = key(t); r = QRectF(o.rect); p.save(); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
        if o.state & QStyle.State_MouseOver: p.setPen(Qt.NoPen); p.setBrush(QColor('#1f1f1f')); p.drawRoundedRect(r.adjusted(0, 1, 0, -1), 6, 6)
        pm = TH.get(k) or COV.get(k)
        if pm is None:
            if k not in GC: GC[k] = gen_cover(t['title'] + t['artist'], 64)
            pm = GC[k]
        wide = r.width() > 150; c = QRectF(r.x() + (6 if wide else (r.width() - 48) / 2), r.center().y() - 24, 48, 48); pa = QPainterPath(); pa.addRoundedRect(c, 4, 4); p.setClipPath(pa); p.drawPixmap(c, pm, QRectF(pm.rect())); p.setClipping(False)
        cur = idx == s.cur
        if not wide:
            if cur: p.setPen(QPen(QColor(ACC), 2)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(c.adjusted(-3, -3, 3, 3), 6, 6)
            p.restore(); return
        x = c.right() + 12; w = r.right() - x - 6
        lines(p, x, r.center().y(), w, t['title'], t['artist'], ACC if cur else '#fff'); p.restore()

class SeekBar(QWidget):
    """Time labels + progress bar painted as ONE widget so text and bar share an exact centre line."""
    sliderMoved = Signal(int)
    def __init__(s):
        super().__init__(); s.mn = s.mx = s.v = 0; s.lt = s.rt = '0:00'; s.down = s.hov = False; s.setFixedHeight(22); s.setMinimumWidth(220); s.setMouseTracking(True); s.setCursor(Qt.PointingHandCursor)
    def setRange(s, a, b): s.mn, s.mx = a, b; s.rt = fmt(b); s.update()
    def setValue(s, v):
        if not s.down: s.v = v; s.lt = fmt(v); s.update()
    def isSliderDown(s): return s.down
    def _geo(s): return 54, s.width() - 54
    def _val(s, x): x0, x1 = s._geo(); return int(s.mn + (s.mx - s.mn) * max(0., min(1., (x - x0) / max(1, x1 - x0))))
    def enterEvent(s, e): s.hov = True; s.update()
    def leaveEvent(s, e): s.hov = False; s.update()
    def _drag(s, e): s.v = s._val(e.position().x()); s.lt = fmt(s.v); s.sliderMoved.emit(s.v); s.update()
    def mousePressEvent(s, e): s.down = True; s._drag(e)
    def mouseMoveEvent(s, e):
        if s.down: s._drag(e)
    def mouseReleaseEvent(s, e): s.down = False; s.update()
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing); cy = s.height() / 2; x0, x1 = s._geo()
        f = QFont('Segoe UI', 9); p.setFont(f); fm = QFontMetricsF(f); base = cy + fm.capHeight() / 2; p.setPen(QColor(DIM))
        p.drawText(QPointF(x0 - 12 - fm.horizontalAdvance(s.lt), base), s.lt); p.drawText(QPointF(x1 + 12, base), s.rt)
        p.setPen(Qt.NoPen); p.setBrush(QColor('#4d4d4d')); p.drawRoundedRect(QRectF(x0, cy - 2, x1 - x0, 4), 2, 2)
        xx = x0 + (x1 - x0) * ((s.v - s.mn) / max(1, s.mx - s.mn)); on = s.hov or s.down
        p.setBrush(QColor(ACC if on else '#fff')); p.drawRoundedRect(QRectF(x0, cy - 2, max(0., xx - x0), 4), 2, 2)
        if on: p.setBrush(QColor('#fff')); p.drawEllipse(QPointF(xx, cy), 6, 6)

class ClickSlider(QSlider):
    def mousePressEvent(s, e):
        v = QStyle.sliderValueFromPosition(s.minimum(), s.maximum(), int(e.position().x()), s.width()); s.setValue(v); s.sliderMoved.emit(v); super().mousePressEvent(e)

class LyricsView(QWidget):
    def __init__(s):
        super().__init__(); s.lines = []; s.synced = False; s.cur = -1; s.off = 0.; s.scr = 0.; s.msg = 'No lyrics yet'
        s.tm = QTimer(s); s.tm.setInterval(16); s.tm.timeout.connect(s.step)
    big = False
    @property
    def LH(s): return 96 if s.big else 54
    def set(s, lines, synced, msg=''): s.lines, s.synced, s.msg, s.cur, s.off, s.scr = lines, synced, msg, -1, 0., 0.; s.update()
    def pos(s, ms):
        if not s.synced: return
        i = -1
        for n, (t, _) in enumerate(s.lines):
            if t <= ms + 120: i = n
            else: break
        if i != s.cur: s.cur = i; s.tm.start()
    def step(s):
        tg = max(0, s.cur) * s.LH; s.off += (tg - s.off) * .10; s.update()
        if abs(tg - s.off) < .5: s.off = tg; s.tm.stop()
    def wheelEvent(s, e):
        if not s.synced: s.scr = max(0, min(s.scr - e.angleDelta().y() / 2, max(0, len(s.lines) * 40 - s.height() + 80))); s.update()
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        f = QFont('Segoe UI', 26 if s.big else 15, QFont.Bold); p.setFont(f)
        if not s.lines: p.setPen(QColor(255, 255, 255, 120)); p.setFont(QFont('Segoe UI', 11)); p.drawText(s.rect().adjusted(14, 0, -14, 0), Qt.AlignCenter | Qt.TextWordWrap, s.msg); return
        for i, (_, tx) in enumerate(s.lines):
            if s.synced:
                y = s.height() / 2 - s.off + i * s.LH - s.LH / 2; d = i - s.cur
                if y < -s.LH or y > s.height(): continue
                p.setPen(QColor(255, 255, 255, 255 if d == 0 else (110 if d > 0 else 70)))
                p.drawText(QRectF(0, y, s.width() - 10, s.LH), Qt.AlignVCenter | (Qt.AlignHCenter if s.big else Qt.AlignLeft) | Qt.TextWordWrap, tx)
            else:
                y = 20 - s.scr + i * (54 if s.big else 40)
                if -40 < y < s.height(): p.setPen(QColor(255, 255, 255, 215)); p.setFont(QFont('Segoe UI', 22 if s.big else 14, QFont.DemiBold)); p.drawText(QRectF(0, y, s.width() - 10, 54 if s.big else 40), Qt.AlignVCenter | (Qt.AlignHCenter if s.big else Qt.AlignLeft), tx)

QSS = """
QLabel{color:#fff;background:transparent}
#panel{background:#121212;border-radius:8px} #bar{background:transparent;border:none}
#h1{font-size:30px;font-weight:800} #h2{font-size:22px;font-weight:700} #dim{color:#b3b3b3}
QLineEdit{background:#242424;border:1px solid transparent;border-radius:6px;padding:8px 12px;color:#fff;font-size:13px} QLineEdit:hover{background:#2a2a2a} QLineEdit:focus{border-color:#fff}
QPushButton{background:#fff;color:#000;border:none;border-radius:18px;padding:9px 20px;font-weight:700} QPushButton:hover{background:#f0f0f0}
QPushButton#green{background:#1db954;color:#000} QPushButton#green:hover{background:#1ed760}
QPushButton#flat{background:transparent;color:#b3b3b3;padding:4px 8px;font-size:12px;font-weight:700} QPushButton#flat:hover{color:#fff}
QPushButton#chip{background:#232323;color:#fff;border:none;border-radius:16px;padding:6px 12px;font-size:12px;font-weight:600} QPushButton#chip:hover{background:#2f2f2f} QPushButton#chip:checked{background:#fff;color:#000}
#topsearch{background:#1f1f1f;border:2px solid transparent;border-radius:23px;padding:0 12px;font-size:14px} #topsearch:hover{background:#2a2a2a;border-color:#3a3a3a} #topsearch:focus{border-color:#fff}
QPushButton#avatar{background:#535353;color:#fff;border-radius:20px;padding:0;font-size:14px;font-weight:700} QPushButton#avatar:hover{background:#6a6a6a}
QFrame#svc{background:#181818;border-radius:8px} QCheckBox{color:#fff;spacing:10px}
QListWidget{background:transparent;border:none;outline:0}
QTableWidget{background:transparent;border:none;color:#fff;font-size:13px;outline:0;selection-background-color:#2a2a2a} QTableWidget::item{padding:6px;border:none}
QTableWidget::item:hover{background:rgba(255,255,255,26)} QHeaderView::section{background:transparent;color:#b3b3b3;border:none;border-bottom:1px solid #2a2a2a;padding:8px 6px;font-size:11px;font-weight:700}
QSlider::groove:horizontal{height:4px;background:#4d4d4d;border-radius:2px} QSlider::sub-page:horizontal{background:#fff;border-radius:2px} QSlider::sub-page:horizontal:hover{background:#1db954}
QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;border-radius:6px;background:#fff}
QScrollArea{background:transparent;border:none} QScrollBar:vertical{background:transparent;width:10px} QScrollBar::handle:vertical{background:#3a3a3a;border-radius:5px;min-height:30px}
QScrollBar::add-line,QScrollBar::sub-line{height:0}
"""

# ================================================================ new design: icon rail, centred search, right-hand now-playing panel
def _logo_fb(n):
    pm = QPixmap(n, n); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); g = QLinearGradient(0, 0, n, n)
    g.setColorAt(0, QColor('#8b7bff')); g.setColorAt(1, QColor('#ff7ab8')); p.setPen(Qt.NoPen); p.setBrush(g); p.drawRoundedRect(QRectF(0, 0, n, n), n * .28, n * .28)
    ic(p, 'note', QRectF(n * .22, n * .22, n * .56, n * .56), QColor('#fff')); p.end(); return pm

def _spot_fb(n):
    pm = QPixmap(n, n); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen); p.setBrush(QColor('#1db954')); p.drawEllipse(QRectF(0, 0, n, n))
    p.setPen(QPen(QColor('#000'), n * .07, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush)
    for k, rr in enumerate((.30, .22, .14)): p.drawArc(QRectF(n * .5 - n * rr, n * (.62 - k * .09) - n * rr * .5, n * rr * 2, n * rr), 25 * 16, 130 * 16)
    p.end(); return pm

def asset(name): return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'assets', name)
def img_pm(name, n):
    src = QPixmap(asset(name))
    if src.isNull(): return None
    out = QPixmap(n, n); out.fill(Qt.transparent); p = QPainter(out); p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform); pa = QPainterPath(); pa.addEllipse(QRectF(0, 0, n, n)); p.setClipPath(pa)
    p.drawPixmap(0, 0, src.scaled(n, n, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)); p.end(); return out
def logo_pm(n): return img_pm('logo.png', n) or _logo_fb(n)
def spot_pm(n): return img_pm('spotify.png', n) or _spot_fb(n)

def ph_pix(n=300):
    pm = QPixmap(n, n); pm.fill(QColor('#0d0d0d')); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); ic(p, 'playc', QRectF(n * .38, n * .38, n * .24, n * .24), QColor('#8c8c8c')); p.end(); return pm

def svc_icon(k, n):
    pm = QPixmap(n, n); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
    if k == 'yt':
        p.setBrush(QColor('#ff0033')); p.drawRoundedRect(QRectF(0, n * .2, n, n * .6), n * .18, n * .18); p.setBrush(QColor('#fff'))
        p.drawPolygon(QPolygonF([QPointF(n * .4, n * .38), QPointF(n * .4, n * .62), QPointF(n * .62, n * .5)]))
    elif k == 'ytm':
        p.setPen(QPen(QColor('#b3b3b3'), 1.5)); p.drawEllipse(QRectF(1, 1, n - 2, n - 2)); p.setPen(Qt.NoPen); p.setBrush(QColor('#b3b3b3'))
        p.drawPolygon(QPolygonF([QPointF(n * .4, n * .3), QPointF(n * .4, n * .7), QPointF(n * .72, n * .5)]))
    else:
        p.setBrush(QColor('#ff7a1a'))
        for i, h in enumerate((.35, .55, .75, .5)): p.drawRoundedRect(QRectF(n * (.08 + i * .24), n * (.5 - h / 2), n * .15, n * h), 1.5, 1.5)
    p.end(); return pm

BGS = [('Black', '#000000', '#070707'), ('Charcoal', '#111113', '#19191c'), ('Midnight', '#050912', '#0c1424'), ('Plum', '#12060f', '#1d0d1a'), ('Forest', '#050e0a', '#0d1b14'), ('Slate', '#0d1117', '#171c24'), ('Cyan glow', '#021214', '#07282d')]

class Swatch(Springy):
    def __init__(s, name, bg, pn): super().__init__(5); s.name, s.bg, s.pn, s.on = name, bg, pn, False; s.setFixedSize(48, 48); s.grow = .12; s.setToolTip(name)
    def draw(s, p, r):
        p.setPen(QPen(QColor(ACC if s.on else '#3a3a3a'), 2.6 if s.on else 1.5)); p.setBrush(QColor(s.bg)); p.drawEllipse(r); p.setPen(Qt.NoPen); p.setBrush(QColor(s.pn)); p.drawEllipse(r.center(), r.width() * .26, r.width() * .26)

class RPanel(QFrame):
    """Right panel: a blurred copy of the cover sits behind the lyrics and crossfades when the song changes."""
    def __init__(s):
        super().__init__(); s.cur = s.old = s.src = None; s.a = 1.; s.base = QColor('#070707')
        s.an = QVariantAnimation(s); s.an.setDuration(1800); s.an.setStartValue(0.); s.an.setEndValue(1.); s.an.valueChanged.connect(s._v)
    def _v(s, v): s.a = v; s.update()
    def _mk(s, pm):
        a = pm.scaled(20, 20, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).scaled(120, 120, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        return a.scaled(s.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    def set_cover(s, pm): s.old = s.cur; s.src = pm; s.cur = s._mk(pm); s.an.stop(); s.an.start()
    def resizeEvent(s, e):
        super().resizeEvent(e)
        if s.src: s.cur = s._mk(s.src); s.old = None
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.Antialiasing); pa = QPainterPath(); pa.addRoundedRect(QRectF(s.rect()).adjusted(.5, .5, -.5, -.5), 22, 22); p.setClipPath(pa); p.fillRect(s.rect(), s.base)
        for pm, op in ((s.old, 1.), (s.cur, s.a)):
            if pm: p.setOpacity(op); p.drawPixmap((s.width() - pm.width()) // 2, (s.height() - pm.height()) // 2, pm)
        p.setOpacity(1); p.fillRect(s.rect(), QColor(0, 0, 0, 150 if s.cur else 0)); p.setClipping(False); p.setPen(QPen(QColor('#1a1a1a'), 1)); p.setBrush(Qt.NoBrush); p.drawPath(pa)

class LogoBtn(Springy):
    def __init__(s): super().__init__(4); s.setFixedSize(52, 52); s.grow = .1; s.pm = logo_pm(44)
    def draw(s, p, r): p.drawPixmap(r.toRect(), s.pm)

class Shortcut(Springy):
    def __init__(s, kind, title, sub): super().__init__(4); s.kind, s.ti, s.su = kind, title, sub; s.setFixedHeight(64); s.setMinimumWidth(180); s.grow = .02; s.pull = .04
    def draw(s, p, r):
        if s.hov: p.setPen(Qt.NoPen); p.setBrush(QColor('#0f0f0f')); p.drawRoundedRect(r, 12, 12)
        c = QRectF(r.x() + 8, r.center().y() - 20, 40, 40); p.setPen(Qt.NoPen); p.setBrush(QColor('#1a1a1a')); p.drawEllipse(c); ic(p, s.kind, c.adjusted(11, 11, -11, -11), QColor('#d0d0d0'))
        lines(p, c.right() + 14, r.center().y(), r.right() - c.right() - 24, s.ti, s.su)

class Card(Springy):
    def __init__(s, t, title=None, sub=None, icon=None):
        super().__init__(8); s.t, s.icon = t, icon; s.ti = title if title is not None else t['title']; s.su = sub if sub is not None else t['artist']
        s.setFixedSize(178, 232); s.grow = .035; s.pull = .05; s.pm = None if icon else (COV.get(key(t)) or gen_cover(t['title'] + t['artist'], 200))
    def draw(s, p, r):
        w = r.width(); pa = QPainterPath(); pa.addRoundedRect(QRectF(r.x(), r.y(), w, w), 14, 14)
        if s.icon: p.setPen(Qt.NoPen); p.setBrush(QColor('#0e0e0e')); p.drawPath(pa); ic(p, s.icon, QRectF(r.center().x() - 24, r.y() + w / 2 - 24, 48, 48), QColor('#8c8c8c'))
        else: p.save(); p.setClipPath(pa); p.drawPixmap(QRectF(r.x(), r.y(), w, w), s.pm, QRectF(s.pm.rect())); p.restore()
        k = max(0., min(1., (s.st[2] - 1) / s.grow)) if s.hov else 0.
        if k: p.setOpacity(k); p.setPen(Qt.NoPen); p.setBrush(QColor('#fff')); c = QRectF(r.right() - 50, r.y() + w - 50 + (1 - k) * 8, 40, 40); p.drawEllipse(c); ic(p, 'play', c.adjusted(12, 12, -12, -12), QColor('#000')); p.setOpacity(1)
        p.setPen(QColor('#fff')); p.setFont(QFont('Segoe UI', 10, QFont.Bold)); p.drawText(QPointF(r.x(), r.y() + w + 24), p.fontMetrics().elidedText(s.ti, Qt.ElideRight, int(w)))
        p.setPen(QColor(DIM)); p.setFont(QFont('Segoe UI', 9)); p.drawText(QPointF(r.x(), r.y() + w + 43), p.fontMetrics().elidedText(s.su, Qt.ElideRight, int(w)))

class SongDelegate(QStyledItemDelegate):
    """Song rows: cover, title/artist, album, heart, duration - painted by hand."""
    def __init__(s, win): super().__init__(win); s.w = win; s.cur = -1
    def sizeHint(s, o, i): return QSize(0, 64)
    def paint(s, p, o, i):
        idx = i.data(Qt.UserRole); t = s.w.T[idx]; k = key(t); r = QRectF(o.rect); p.save(); p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        if o.state & QStyle.State_MouseOver: p.setPen(Qt.NoPen); p.setBrush(QColor('#101010')); p.drawRoundedRect(r.adjusted(0, 2, 0, -2), 12, 12)
        pm = TH.get(k) or COV.get(k)
        if pm is None:
            if k not in GC: GC[k] = gen_cover(t['title'] + t['artist'], 64)
            pm = GC[k]
        c = QRectF(r.x() + 10, r.center().y() - 24, 48, 48); pa = QPainterPath(); pa.addRoundedRect(c, 8, 8); p.setClipPath(pa); p.drawPixmap(c, pm, QRectF(pm.rect())); p.setClipping(False)
        lines(p, c.right() + 14, r.center().y(), r.width() * .36, t['title'], t['artist'], ACC if idx == s.cur else '#fff')
        f = QFont('Segoe UI', 9); p.setFont(f); fm = QFontMetricsF(f); yb = r.center().y() + fm.capHeight() / 2; p.setPen(QColor(DIM))
        p.drawText(QPointF(r.x() + r.width() * .55, yb), fm.elidedText(t['album'] or t['src'], Qt.ElideRight, r.width() * .22))
        d = fmt(t['dur']) if t['dur'] else ''; p.drawText(QPointF(r.right() - 18 - fm.horizontalAdvance(d), yb), d)
        if k in s.w.liked: ic(p, 'heartf', QRectF(r.right() - 74, r.center().y() - 8, 16, 16), QColor(ACC))
        p.restore()

QSS = """
QLabel{color:#fff;background:transparent}
#rail,#bar{background:#000;border:none} #rpanel{background:#070707;border:1px solid #131313;border-radius:22px}
#hotbar{background:rgba(0,0,0,120);border-radius:20px} QPlainTextEdit{background:#0e0e0e;border:1px solid #222;border-radius:10px;color:#fff;padding:8px;selection-background-color:#33d6e8}
#banner{background:#0a0a0a;border:1px solid #161616;border-radius:18px}
#h1{font-size:28px;font-weight:700} #h2{font-size:20px;font-weight:700} #dim{color:#8c8c8c;font-size:12px}
#topsearch{background:transparent;border:1px solid transparent;border-radius:22px;padding:0 10px;font-size:15px;color:#fff} #topsearch:hover{background:#0c0c0c} #topsearch:focus{background:#0e0e0e;border-color:#2a2a2a}
QLineEdit{background:#161616;border:1px solid #222;border-radius:8px;padding:8px 12px;color:#fff}
QPushButton{background:#fff;color:#000;border:none;border-radius:18px;padding:9px 20px;font-weight:700} QPushButton:hover{background:#ececec}
QPushButton#grey{background:#6f6f6f;color:#fff} QPushButton#grey:hover{background:#858585}
QPushButton#svcpill{background:transparent;color:#fff;border:none;border-radius:16px;padding:7px 12px;font-size:13px;font-weight:600} QPushButton#svcpill:hover{background:#141414}
QFrame#svc{background:#0b0b0b;border:1px solid #161616;border-radius:14px} QCheckBox{color:#fff;spacing:10px}
QListWidget{background:transparent;border:none;outline:0}
QSlider::groove:horizontal{height:4px;background:#2c2c2c;border-radius:2px} QSlider::sub-page:horizontal{background:#fff;border-radius:2px} QSlider::sub-page:horizontal:hover{background:#33d6e8}
QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;border-radius:6px;background:#fff}
QScrollArea{background:transparent;border:none} QScrollBar:vertical{background:transparent;width:8px} QScrollBar::handle:vertical{background:#262626;border-radius:4px;min-height:30px}
QScrollBar::add-line,QScrollBar::sub-line{height:0}
"""

class Win(QWidget):
    def __init__(s):
        super().__init__(); s.setWindowTitle('Bubble'); s.setWindowIcon(QIcon(asset('logo.png'))); s.resize(1340, 830); s.setMinimumSize(1000, 660)
        pal = s.palette(); pal.setColor(QPalette.Window, QColor('#000')); s.setPalette(pal); s.setAutoFillBackground(True)
        s.cfg = load_cfg(); s.T = []; s.keys = set(); s.i = -1; s.shuf = False; s.rep = 0; s.cols = 6; s.loading = set(); s.cards = []; s.homekeys = set(); s.lists = []; s.full = False
        s.liked = set(s.cfg.get('liked', [])); s.cq = queue.Queue(); threading.Thread(target=cover_worker, args=(s.cq,), daemon=True).start(); s.dg = SongDelegate(s)
        s.pl = QMediaPlayer(s); s.ao = QAudioOutput(s); s.pl.setAudioOutput(s.ao); s.ao.setVolume(.8); PH['C'] = s.cfg.get('damp', .30)
        s.hdeb = QTimer(s); s.hdeb.setSingleShot(True); s.hdeb.setInterval(400); s.hdeb.timeout.connect(s.home_refresh)
        root = QVBoxLayout(s); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0); body = QHBoxLayout(); body.setSpacing(0); root.addLayout(body, 1)
        s.railw = s.mk_rail(); body.addWidget(s.railw); s.midw = QWidget(); mid = QVBoxLayout(s.midw); mid.setContentsMargins(0, 0, 0, 0); mid.setSpacing(0); mid.addLayout(s.mk_top()); s.stack = QStackedWidget(); mid.addWidget(s.stack, 1); body.addWidget(s.midw, 1)
        for pg in (s.mk_home(), s.mk_songs('Library', True), s.mk_songs('Liked songs'), s.mk_songs('Recently played'), s.mk_settings()): s.stack.addWidget(pg)
        body.addWidget(s.mk_rpanel()); root.addWidget(s.mk_bar())
        B.imported.connect(s.add_tracks); B.cover.connect(s.on_cover); B.resolved.connect(s.on_resolved); B.lyrics.connect(s.on_lyrics); B.status.connect(lambda m: s.note.setText(m))
        s.pl.positionChanged.connect(s.on_pos); s.pl.durationChanged.connect(lambda d: s.seek.setRange(0, d))
        s.pl.mediaStatusChanged.connect(lambda m: s.step(1, auto=True) if m == QMediaPlayer.MediaStatus.EndOfMedia else None)
        s.pl.playbackStateChanged.connect(lambda _: s.bplay.__setattr__('kind', 'pause' if s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState else 'play') or s.bplay.update())
        s.apply_bg(s.cfg.get('bg', 'Black'), False); s.go(0); s.add_tracks(s.cfg.get('remote', []), save=False)
        fl = s.cfg.get('folders', [])
        if fl: threading.Thread(target=s.scan, args=(fl,), daemon=True).start()

    # ---- frame
    def mk_rail(s):
        r = QFrame(); r.setObjectName('rail'); r.setFixedWidth(76); v = QVBoxLayout(r); v.setContentsMargins(0, 14, 0, 14); v.setSpacing(6); s.rail = {}
        lg = LogoBtn(); lg.clicked.connect(lambda: s.go(0)); v.addWidget(lg, 0, Qt.AlignHCenter); v.addSpacing(20)
        for k, pg in (('heart', 2), ('folder', 1), ('clock', 3)):
            b = IconBtn(k, 26, False, 9); b.clicked.connect(lambda pg=pg: s.go(pg)); s.rail[pg] = b; v.addWidget(b, 0, Qt.AlignHCenter)
        v.addSpacing(12)
        for k, f in (('sliders', lambda: s.go(4)), ('lyrics', lambda: s.toggle_rp())):
            b = IconBtn(k, 40, 'grey', 4); b.clicked.connect(f); v.addWidget(b, 0, Qt.AlignHCenter)
        v.addStretch(); g = IconBtn('gear', 26, False, 9); g.clicked.connect(lambda: s.go(4)); s.rail[4] = g; v.addWidget(g, 0, Qt.AlignHCenter); return r
    def mk_top(s):
        h = QHBoxLayout(); h.setContentsMargins(24, 14, 24, 6); h.setSpacing(6); h.addStretch(1)
        s.q = QLineEdit(); s.q.setObjectName('topsearch'); s.q.setPlaceholderText('Search tracks, artists, or albums...'); s.q.setFixedSize(520, 44)
        s.q.addAction(QIcon(glyph('search', 22, '#b3b3b3')), QLineEdit.LeadingPosition); s.q.textChanged.connect(s.on_search); h.addWidget(s.q); h.addStretch(1)
        for name, k in (('YouTube', 'yt'), ('YouTube Music', 'ytm'), ('SoundCloud', 'sc')):
            b = QPushButton(' ' + name); b.setObjectName('svcpill'); b.setIcon(QIcon(svc_icon(k, 18))); b.setIconSize(QSize(18, 18)); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: s.link(n)); h.addWidget(b)
        return h
    def mk_rpanel(s):
        f = RPanel(); f.setObjectName('rpanel'); f.setFixedWidth(310); s.rp = f; v = QVBoxLayout(f); v.setContentsMargins(16, 12, 16, 16); v.setSpacing(12)
        hr = QHBoxLayout(); t = QLabel('Now playing'); t.setObjectName('dim'); hr.addStretch(); hr.addWidget(t); x = IconBtn('close', 14, False, 6); x.clicked.connect(s.toggle_rp); hr.addWidget(x); v.addLayout(hr)
        s.rcov = Cov(240, 18, .03, 8); s.rcov.set(ph_pix()); v.addWidget(s.rcov, 0, Qt.AlignHCenter)
        s.rt = QLabel('No track playing'); s.rt.setStyleSheet('font-size:17px;font-weight:700'); s.rt.setAlignment(Qt.AlignCenter); s.rt.setWordWrap(True)
        s.ra = QLabel('Select a track to listen'); s.ra.setObjectName('dim'); s.ra.setAlignment(Qt.AlignCenter); v.addWidget(s.rt); v.addWidget(s.ra)
        hb = QFrame(); hb.setObjectName('hotbar'); hl = QHBoxLayout(hb); hl.setContentsMargins(8, 1, 8, 1); hl.setSpacing(2)
        for k, tip, fn in (('pencil', 'Write lyrics', s.write_lyrics), ('import', 'Import lyrics file', s.import_lyrics), ('refresh', 'Reload lyrics', s.reload_lyrics), ('expand', 'Fullscreen lyrics', s.toggle_full)):
            b = IconBtn(k, 18, False, 7); b.setToolTip(tip); b.clicked.connect(fn); hl.addWidget(b)
        v.addWidget(hb, 0, Qt.AlignHCenter); s.lv = LyricsView(); v.addWidget(s.lv, 1); return f
    def mk_bar(s):
        bar = QFrame(); bar.setObjectName('bar'); bar.setFixedHeight(96); h = QHBoxLayout(bar); h.setContentsMargins(14, 6, 18, 6)
        s.mini = Cov(56, 28, .05, 6); s.mini.set(ph_pix(120)); s.mini.clicked.connect(s.toggle_rp)
        inf = QVBoxLayout(); inf.setSpacing(2); inf.addStretch(); s.bt = QLabel('No track playing'); s.bt.setStyleSheet('font-weight:700;font-size:14px'); s.ba = QLabel('Select a track to listen'); s.ba.setObjectName('dim')
        inf.addWidget(s.bt); inf.addWidget(s.ba); inf.addStretch(); s.heart = IconBtn('heart', 20, False, 8); s.heart.clicked.connect(lambda: s.like(s.i))
        L = QHBoxLayout(); L.addWidget(s.mini); L.addLayout(inf, 1); L.addWidget(s.heart); lw = QWidget(); lw.setLayout(L); h.addWidget(lw, 3)
        C = QVBoxLayout(); C.setSpacing(0); r = QHBoxLayout(); r.setSpacing(8); r.addStretch()
        s.bsh = IconBtn('shuffle', 20); s.bpv = IconBtn('prev', 22); s.bplay = IconBtn('play', 36, True); s.bnx = IconBtn('next', 22); s.brp = IconBtn('repeat', 20)
        s.bsh.clicked.connect(lambda: s.flag('shuf')); s.bpv.clicked.connect(lambda: s.step(-1)); s.bplay.clicked.connect(s.toggle); s.bnx.clicked.connect(lambda: s.step(1)); s.brp.clicked.connect(lambda: s.flag('rep'))
        for b in (s.bsh, s.bpv, s.bplay, s.bnx, s.brp): r.addWidget(b)
        r.addStretch(); C.addLayout(r); s.seek = SeekBar(); s.seek.sliderMoved.connect(s.pl.setPosition); C.addWidget(s.seek); cw = QWidget(); cw.setLayout(C); h.addWidget(cw, 4)
        R = QHBoxLayout(); R.addStretch(); ly = IconBtn('lyrics', 20); ly.clicked.connect(s.toggle_rp); vi = IconBtn('vol', 20); s.vol = ClickSlider(Qt.Horizontal); s.vol.setRange(0, 100); s.vol.setValue(80); s.vol.setFixedWidth(110)
        s.vol.valueChanged.connect(lambda v: s.ao.setVolume(v / 100)); R.addWidget(ly); R.addWidget(vi); R.addWidget(s.vol); rw = QWidget(); rw.setLayout(R); h.addWidget(rw, 3); return bar

    # ---- pages
    def sec(s, title, kind, right=None):
        w = QWidget(); r = QHBoxLayout(w); r.setContentsMargins(0, 28, 0, 10); r.setSpacing(10); i = QLabel(); i.setPixmap(glyph(kind, 22, '#ffffff')); r.addWidget(i)
        t = QLabel(title); t.setObjectName('h2'); r.addWidget(t); r.addStretch()
        if right: r.addWidget(right)
        return w
    def mk_home(s):
        sc = QScrollArea(); sc.setWidgetResizable(True); w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(48, 10, 24, 24); v.setSpacing(0)
        bn = QFrame(); bn.setObjectName('banner'); s.banner = bn; b = QHBoxLayout(bn); b.setContentsMargins(22, 16, 18, 16); b.setSpacing(12)
        l1 = QLabel(); l1.setPixmap(spot_pm(52)); b.addWidget(l1); ar = QLabel('\u2192'); ar.setStyleSheet('font-size:22px'); b.addWidget(ar); l2 = QLabel(); l2.setPixmap(logo_pm(52)); b.addWidget(l2); b.addSpacing(8)
        tx = QVBoxLayout(); tx.setSpacing(2); t1 = QLabel('Bring your Spotify music into Bubble'); t1.setStyleSheet('font-size:16px;font-weight:700'); t2 = QLabel('Connect once and your Liked Songs show up here'); t2.setObjectName('dim')
        tx.addWidget(t1); tx.addWidget(t2); b.addLayout(tx); b.addStretch(); ib = QPushButton('Import'); ib.setObjectName('grey'); ib.clicked.connect(s.sp); b.addWidget(ib)
        cx = IconBtn('close', 14, False, 8); cx.clicked.connect(s.close_banner); b.addWidget(cx); bn.setVisible(not s.cfg.get('banner_closed')); v.addWidget(bn)
        rf = IconBtn('refresh', 18, False, 6); rf.clicked.connect(lambda: s.home_refresh(True)); v.addWidget(s.sec('For you', 'wave', rf))
        s.row1 = QHBoxLayout(); s.row1.setSpacing(4); v.addLayout(s.row1)
        s.sec_rec = s.sec('Recommended for you', 'wave'); v.addWidget(s.sec_rec); s.row3 = QHBoxLayout(); s.row3.setSpacing(4); v.addLayout(s.row3)
        s.sec_top = s.sec('Popular with you', 'library'); v.addWidget(s.sec_top); s.row4 = QHBoxLayout(); s.row4.setSpacing(4); v.addLayout(s.row4)
        v.addWidget(s.sec('Home', 'home')); sr = QHBoxLayout(); sr.setSpacing(8)
        s.sc_like = Shortcut('heart', 'Liked songs', '0 songs'); s.sc_like.clicked.connect(lambda: s.go(2)); s.sc_rec = Shortcut('clock', 'Recently played', 'Pick up where you left off'); s.sc_rec.clicked.connect(lambda: s.go(3))
        s.sc_lib = Shortcut('folder', 'Your library', '0 songs'); s.sc_lib.clicked.connect(lambda: s.go(1))
        for x in (s.sc_like, s.sc_rec, s.sc_lib): sr.addWidget(x)
        sr.addStretch(); v.addLayout(sr); s.sec_new = s.sec('Recently added', 'library'); v.addWidget(s.sec_new); s.row2 = QHBoxLayout(); s.row2.setSpacing(4); v.addLayout(s.row2)
        s.hint = QLabel('Your music will show up here.'); s.hint.setObjectName('dim'); v.addSpacing(16); v.addWidget(s.hint); v.addSpacing(8)
        s.hbtn = QPushButton('Import music folder'); s.hbtn.setObjectName('grey'); s.hbtn.clicked.connect(s.add_folder); v.addWidget(s.hbtn, 0, Qt.AlignLeft); v.addStretch()
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.viewport().setAutoFillBackground(False); sc.setWidget(w); s.hw = sc; return sc
    def mk_songs(s, title, lib=False):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(48, 10, 24, 12); v.setSpacing(10); r = QHBoxLayout(); t = QLabel(title); t.setObjectName('h1'); r.addWidget(t); r.addStretch()
        if lib: b = QPushButton('Import folder'); b.setObjectName('grey'); b.clicked.connect(s.add_folder); r.addWidget(b)
        v.addLayout(r); l = QListWidget(); l.setFrameShape(QFrame.NoFrame); l.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); l.setMouseTracking(True); l.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); l.setItemDelegate(s.dg)
        l.itemClicked.connect(lambda it: s.play(it.data(Qt.UserRole))); v.addWidget(l, 1); s.lists.append(l); return w
    def fill(s, l, idxs):
        l.clear()
        for n in idxs: it = QListWidgetItem(); it.setData(Qt.UserRole, n); l.addItem(it)
    def go(s, n):
        s.stack.setCurrentIndex(n)
        if n == 2: s.fill(s.lists[1], [i for i, t in enumerate(s.T) if key(t) in s.liked])
        if n == 3: kidx = {key(t): i for i, t in enumerate(s.T)}; s.fill(s.lists[2], [kidx[k] for k in s.cfg.get('recent', []) if k in kidx])
        for pg, b in s.rail.items(): b.on = pg == n; b.update()
    def on_search(s, txt):
        q = txt.lower(); l = s.lists[0]
        for r in range(l.count()): it = l.item(r); t = s.T[it.data(Qt.UserRole)]; it.setHidden(bool(q) and q not in (t['title'] + t['artist'] + t['album']).lower())
        if txt and s.stack.currentIndex() != 1: s.go(1)
    def add_bg(s, v):
        c = QLabel('Background'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c); r = QHBoxLayout(); r.setSpacing(10); s.sw = []
        for n, bg, pn in BGS: b = Swatch(n, bg, pn); b.clicked.connect(lambda n=n: s.apply_bg(n)); s.sw.append(b); r.addWidget(b)
        r.addStretch(); v.addLayout(r)
    def apply_bg(s, name, save=True):
        bg, pn = next((b, p) for n, b, p in BGS if n == name); pal = s.palette(); pal.setColor(QPalette.Window, QColor(bg)); s.setPalette(pal)
        QApplication.instance().setStyleSheet(QSS.replace('#rail,#bar{background:#000', '#rail,#bar{background:' + bg).replace('#070707', pn).replace('#0a0a0a', pn).replace('#0b0b0b', pn))
        s.rp.base = QColor(pn); s.rp.update()
        for b in s.sw: b.on = b.name == name; b.update()
        if save: s.cfg['bg'] = name; save_cfg(s.cfg)
    def card_icon(s, r, n):
        pm = spot_pm(40) if n == 'Spotify' else svc_icon('ytm', 36) if n == 'YouTube Music' else svc_icon('sc', 36) if n == 'SoundCloud' else None
        if pm: l = QLabel(); l.setPixmap(pm); r.addWidget(l)
    def close_banner(s): s.banner.hide(); s.cfg['banner_closed'] = True; save_cfg(s.cfg)
    def toggle_rp(s): s.rp.setVisible(not s.rp.isVisible())
    def reload_lyrics(s):
        if s.i >= 0: s.set_lyrics(s.i, s.T[s.i], s.cfg.get('lyrics', {}).get(key(s.T[s.i])))
    def lyric_text(s):
        c = s.cfg.get('lyrics', {}).get(key(s.T[s.i]))
        if c: return c
        if s.lv.synced: return '\n'.join(f'[{ms // 60000:02d}:{(ms % 60000) / 1000:05.2f}]{tx}' for ms, tx in s.lv.lines)
        return '\n'.join(tx for _, tx in s.lv.lines)
    def save_lyrics(s, t, txt):
        ly = s.cfg.setdefault('lyrics', {})
        if txt.strip(): ly[key(t)] = txt
        else: ly.pop(key(t), None)
        save_cfg(s.cfg); s.set_lyrics(s.i, t, txt.strip() or None)
    def write_lyrics(s):
        if s.i < 0: return
        t = s.T[s.i]; d = QDialog(s); d.setWindowTitle('Write lyrics'); d.resize(540, 580); v = QVBoxLayout(d)
        hl = QLabel('Type or paste lyrics for "' + t['title'] + '". Add [mm:ss.xx] timestamps at the start of lines to make them scroll in time. Clear the box to go back to automatic lyrics.'); hl.setWordWrap(True); hl.setObjectName('dim'); v.addWidget(hl)
        ed = QPlainTextEdit(); ed.setPlainText(s.lyric_text()); v.addWidget(ed, 1); r = QHBoxLayout(); r.addStretch(); c = QPushButton('Cancel'); c.setObjectName('grey'); ok = QPushButton('Save'); r.addWidget(c); r.addWidget(ok); v.addLayout(r)
        c.clicked.connect(d.reject); ok.clicked.connect(d.accept)
        if d.exec(): s.save_lyrics(t, ed.toPlainText())
    def import_lyrics(s):
        if s.i < 0: return
        f = QFileDialog.getOpenFileName(s, 'Import lyrics', '', 'Lyrics (*.lrc *.txt);;All files (*)')[0]
        if not f: return
        try: txt = open(f, encoding='utf-8-sig', errors='ignore').read()
        except Exception as e: B.status.emit(f'Could not read file: {e}'); return
        s.save_lyrics(s.T[s.i], txt)
    def toggle_full(s):
        s.full = not s.full; s.rp.setVisible(True); s.railw.setVisible(not s.full); s.midw.setVisible(not s.full); s.lv.big = s.full
        if s.full: s.rp.setMinimumWidth(0); s.rp.setMaximumWidth(16777215); s.rp.layout().setContentsMargins(160, 24, 160, 24); s.showFullScreen()
        else: s.rp.setFixedWidth(310); s.rp.layout().setContentsMargins(16, 12, 16, 16); s.showNormal()
        s.lv.off = max(0, s.lv.cur) * s.lv.LH; s.lv.update()
    def shuffle_all(s):
        if s.T: s.shuf = True; s.bsh.on = True; s.bsh.update(); s.play(random.randrange(len(s.T)))
    def like(s, i):
        if i < 0: return
        k = key(s.T[i]); (s.liked.discard(k) if k in s.liked else s.liked.add(k)); s.cfg['liked'] = sorted(s.liked); save_cfg(s.cfg); s.refresh_heart()
        for l in s.lists: l.viewport().update()
        s.sc_like.su = f'{len(s.liked)} songs'; s.sc_like.update()
    def refresh_heart(s):
        on = s.i >= 0 and key(s.T[s.i]) in s.liked; s.heart.kind = 'heartf' if on else 'heart'; s.heart.on = on; s.heart.update()
    def resizeEvent(s, e):
        super().resizeEvent(e)
        if s.T and max(1, (s.hw.width() - 80) // 182) != s.cols: QTimer.singleShot(0, s.home_refresh)
    def home_refresh(s, shuf=False):
        for g in (s.row1, s.row2, s.row3, s.row4):
            while g.count():
                w = g.takeAt(0).widget()
                if w: w.deleteLater()
        s.cards = []; s.homekeys = set(); lib = [n for n, t in enumerate(s.T) if not t.get('rec')]; e = not lib; s.hint.setVisible(e); s.hbtn.setVisible(e); s.sec_new.setVisible(not e)
        s.cols = max(1, (s.hw.width() - 80) // 182); kidx = {key(s.T[n]): n for n in lib}; order = [kidx[k] for k in s.cfg.get('recent', []) if k in kidx]; order += [n for n in lib if n not in order]
        if shuf: random.shuffle(order)
        def add(row, n):
            c = Card(s.T[n]); c.clicked.connect(lambda n=n: s.play(n)); s.cards.append(c); row.addWidget(c); s.homekeys.add(key(s.T[n])); s.want(s.T[n], True, True)
        if lib: fc = Card(None, 'For you', 'Shuffle your whole library', 'note'); fc.clicked.connect(s.shuffle_all); s.row1.addWidget(fc)
        for n in order[:s.cols - 1]: add(s.row1, n)
        for n in lib[::-1][:s.cols]: add(s.row2, n)
        rec = [n for n, t in enumerate(s.T) if t.get('rec') == 'rec']; top = [n for n, t in enumerate(s.T) if t.get('rec') == 'top']; s.sec_rec.setVisible(bool(rec)); s.sec_top.setVisible(bool(top))
        for n in rec[:s.cols]: add(s.row3, n)
        for n in top[:s.cols]: add(s.row4, n)
        for g in (s.row1, s.row2, s.row3, s.row4): g.addStretch()
        s.sc_lib.su = f'{len(lib)} songs'; s.sc_lib.update(); s.sc_like.su = f'{len(s.liked)} songs'; s.sc_like.update()

    # ---- library + covers
    def add_tracks(s, lst, save=True):
        new = [t for t in lst if key(t) not in s.keys]
        if not new: return
        for t in new:
            s.keys.add(key(t)); s.T.append(t); it = QListWidgetItem(); it.setData(Qt.UserRole, len(s.T) - 1); (s.lists[0].addItem(it) if not t.get('rec') else None); s.want(t, False)
        rem = [t for t in new if t['src'] != 'Local']
        if rem and save: s.cfg.setdefault('remote', []).extend(rem); save_cfg(s.cfg)
        B.status.emit(f'{len(s.T)} songs in your library'); s.hdeb.start()
    def on_cover(s, k, img):
        TH[k] = QPixmap.fromImage(img.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        for l in s.lists: l.viewport().update()
        if k in s.homekeys:
            pm = QPixmap.fromImage(img); COV[k] = pm
            for c in s.cards:
                try:
                    if c.t and key(c.t) == k: c.pm = pm; c.update()
                except RuntimeError: pass

    # ---- playback
    def play(s, i):
        if s.note.text().startswith('Loading'): s.note.setText('')
        s.i = i; t = s.T[i]; rc = s.cfg.setdefault('recent', []); rc[:] = [key(t)] + [x for x in rc if x != key(t)]; del rc[30:]; save_cfg(s.cfg); s.dg.cur = i
        s.pl.stop(); s.bt.setText(t['title']); s.ba.setText(t['artist']); s.rt.setText(t['title']); s.ra.setText(t['artist']); s.refresh_heart()
        pm = COV.get(key(t)); lyr = None
        if t['path']:
            s.pl.setSource(QUrl.fromLocalFile(t['path'])); s.pl.play(); cov, lyr = extras(t['path']) if mutagen else (None, None)
            if cov: q = QPixmap(); q.loadFromData(cov); pm = q if not q.isNull() else pm
        else: B.status.emit('Loading stream...'); threading.Thread(target=s.res, args=(i, t), daemon=True).start()
        s.set_cover(t, pm or gen_cover(t['title'] + t['artist'])); s.set_lyrics(i, t, s.cfg.get('lyrics', {}).get(key(t)) or lyr)
        for l in s.lists: l.viewport().update()
    def set_cover(s, t, pm): COV[key(t)] = sq(pm, 360); s.mini.set(pm); s.rcov.set(pm); s.rp.set_cover(pm)

    def scan(s, folders):
        out = []
        for f in folders:
            for root, _, fs in os.walk(f):
                for n in sorted(fs):
                    if n.lower().endswith(EXT):
                        out.append(tag(os.path.join(root, n)))
                        if len(out) >= 40: B.imported.emit(out); out = []
        if out: B.imported.emit(out)
    def add_folder(s):
        d = QFileDialog.getExistingDirectory(s, 'Choose your music folder')
        if d:
            fl = s.cfg.setdefault('folders', [])
            if d not in fl: fl.append(d); save_cfg(s.cfg)
            s.fl_upd(); B.status.emit('Scanning ' + d + ' ...'); threading.Thread(target=s.scan, args=([d],), daemon=True).start(); s.go(1)
    def fl_upd(s): s.fl.setText('\n'.join(s.cfg.get('folders', [])) or 'No folders yet.')
    def run(s, fn, ok):
        def job():
            try: out = fn(); B.imported.emit(out); (B.status.emit(f'{ok}: {len(out)} songs imported') if out else None)
            except ImportError: B.status.emit('This needs yt-dlp. Run: pip install yt-dlp')
            except Exception as e: B.status.emit(f'Import failed: {e}' + (' - use Import data export instead.' if 'Premium' in str(e) else ''))
        threading.Thread(target=job, daemon=True).start()
    def sp(s):
        if not s.cfg.get('sp_nowarn'):
            m = QMessageBox(s); m.setWindowTitle('Spotify Premium required'); m.setIcon(QMessageBox.Warning)
            m.setText('Spotify only lets apps use its Web API when the Spotify account that owns the app has Premium. On a free account, Connect will fail with a 403 error.')
            m.setInformativeText("No Premium? Choose Use data export instead. It imports your saved songs, playlists and most-played tracks from the files on Spotify's Download your data page, with no Premium needed.")
            cb = QCheckBox("I have Premium - don't show this again"); m.setCheckBox(cb)
            go = m.addButton('Connect anyway', QMessageBox.AcceptRole); ex = m.addButton('Use data export', QMessageBox.ActionRole); m.addButton('Cancel', QMessageBox.RejectRole); m.exec()
            if m.clickedButton() is ex: s.sp_files(); return
            if m.clickedButton() is not go: return
            if cb.isChecked(): s.cfg['sp_nowarn'] = True; save_cfg(s.cfg)
        s.sp_connect()
    def sp_connect(s):
        cid = s.cfg.get('spotify_id') or QInputDialog.getText(s, 'Spotify', 'Paste your Spotify Client ID\n(create a free app at developer.spotify.com and add the redirect URI http://127.0.0.1:8888/callback):')[0].strip()
        if cid: s.cfg['spotify_id'] = cid; save_cfg(s.cfg); B.status.emit('Waiting for Spotify login in your browser...'); s.run(lambda: spotify_liked(cid), 'Spotify')
    def sp_files(s):
        fs = QFileDialog.getOpenFileNames(s, 'Choose YourLibrary.json, Playlist and/or StreamingHistory files from your Spotify data download', '', 'Spotify data (*.json)')[0]
        if fs: B.status.emit('Importing...'); s.run(lambda: spotify_files(fs), 'Spotify')
    def link(s, src):
        u, ok = QInputDialog.getText(s, src, f'Paste a {src} song, album or playlist link:')
        if ok and u.strip(): B.status.emit('Importing...'); s.run(lambda: yt_import(u.strip(), src), src)
    def apple(s):
        f = QFileDialog.getOpenFileName(s, 'Apple Music library file', '', 'Library (*.xml *.plist)')[0]
        if f: s.run(lambda: apple_import(f), 'Apple Music')
    def bounce(s, v): PH['C'] = .5 - v / 100 * .30; s.cfg['damp'] = PH['C']; save_cfg(s.cfg)

    # ---- playback
    def res(s, i, t):
        try: u, d = resolve(t); B.resolved.emit(i, u, d)
        except ImportError: B.status.emit('Streaming needs yt-dlp. Run: pip install yt-dlp')
        except Exception as e: B.status.emit(f'Could not load stream: {e}')
    def on_resolved(s, i, url, data):
        if i != s.i: return
        s.pl.setSource(QUrl(url)); s.pl.play(); s.note.setText('')
        if data:
            q = QPixmap(); q.loadFromData(data)
            if not q.isNull(): s.set_cover(s.T[i], q)
    def set_lyrics(s, i, t, txt):
        if txt: s.lv.set(*parse_lrc(txt))
        else:
            s.lv.set([], False, 'Searching for lyrics...' if s.cfg.get('lyrics_online', True) else 'No lyrics found')
            if s.cfg.get('lyrics_online', True): threading.Thread(target=s.web_lyrics, args=(i, t), daemon=True).start()
    def web_lyrics(s, i, t):
        pick = lambda j: (j.get('syncedLyrics') or j.get('plainLyrics') or '') if isinstance(j, dict) else ''; txt = ''; a = '' if t['artist'].startswith('Unknown') else t['artist']
        try: txt = pick(fetch('https://lrclib.net/api/get?' + urllib.parse.urlencode(dict(artist_name=a, track_name=t['title'], album_name=t['album'], duration=t['dur'] // 1000))))
        except Exception: pass
        for q in (dict(track_name=t['title'], artist_name=a), dict(q=(a + ' ' + t['title']).strip())):
            if txt: break
            try:
                res = fetch('https://lrclib.net/api/search?' + urllib.parse.urlencode({k: v for k, v in q.items() if v}))
                txt = next((pick(r) for r in res if r.get('syncedLyrics')), '') or next((pick(r) for r in res if r.get('plainLyrics')), '')
            except Exception: pass
        B.lyrics.emit(i, txt)
    def on_lyrics(s, i, txt):
        if i == s.i: s.lv.set(*parse_lrc(txt)) if txt else s.lv.set([], False, 'No lyrics found for this song')
    def on_pos(s, ms):
        if not s.seek.isSliderDown(): s.seek.setValue(ms)
        s.lv.pos(ms)
    def toggle(s):
        if s.i < 0 and s.T: s.play(0)
        elif s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState: s.pl.pause()
        else: s.pl.play()
    def step(s, d, auto=False):
        if not s.T: return
        if auto and s.rep == 2: s.pl.setPosition(0); s.pl.play(); return
        if auto and s.rep == 0 and not s.shuf and s.i >= len(s.T) - 1: return
        if not auto and d < 0 and s.pl.position() > 3000: s.pl.setPosition(0); return
        s.play(random.randrange(len(s.T)) if s.shuf else (s.i + d) % len(s.T))
    def flag(s, k):
        if k == 'shuf': s.shuf = not s.shuf; s.bsh.on = s.shuf; s.bsh.update()
        else: s.rep = (s.rep + 1) % 3; s.brp.on = s.rep > 0; s.brp.update()
    def keyPressEvent(s, e):
        if e.key() == Qt.Key_Space and not isinstance(s.focusWidget(), QLineEdit): s.toggle()
        elif e.key() == Qt.Key_Escape and s.full: s.toggle_full()
        else: super().keyPressEvent(e)
    def want(s, t, remote=True, force=False):
        k = key(t)
        if k in COV or (not force and (k in TH or k in s.loading)): return
        if t['path'] or (remote and t['cover_url']): s.loading.add(k); s.cq.put((k, t['path'], t['cover_url']))
    def mk_settings(s):
        sc = QScrollArea(); sc.setWidgetResizable(True); w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(28, 24, 28, 24); v.setSpacing(10); sc.viewport().setAutoFillBackground(False)
        t = QLabel('Settings'); t.setObjectName('h1'); v.addWidget(t); s.note = QLabel(''); s.note.setStyleSheet('color:#9a9a9a'); v.addWidget(s.note)
        c = QLabel('Connections'); c.setObjectName('h2'); v.addSpacing(8); v.addWidget(c)
        d = QLabel('Import your music from other services. Imported songs show up in Library and play inside this app.'); d.setObjectName('dim'); d.setWordWrap(True); v.addWidget(d)
        for n, ds, bt, fn in [('Spotify', 'Connect needs Spotify Premium (Spotify blocks its Web API for free accounts). No Premium? Use Import data export with the files from the Download your data page on spotify.com. Songs play via YouTube match.', 'Connect', s.sp),
                              ('YouTube Music', 'Paste a song, album or playlist link. Streams audio directly. Needs yt-dlp.', 'Import link', lambda: s.link('YouTube Music')),
                              ('SoundCloud', 'Paste a track or playlist link. Streams audio directly. Needs yt-dlp.', 'Import link', lambda: s.link('SoundCloud')),
                              ('Apple Music', 'Import a library exported from the Music app (File > Library > Export Library). Only songs saved as files can play; Apple blocks streaming.', 'Import library file', s.apple)]:
            f = QFrame(); f.setObjectName('svc'); r = QHBoxLayout(f); r.setContentsMargins(18, 14, 18, 14); s.card_icon(r, n); col = QVBoxLayout(); a = QLabel(n); a.setStyleSheet('font-size:16px;font-weight:700')
            b = QLabel(ds); b.setObjectName('dim'); b.setWordWrap(True); col.addWidget(a); col.addWidget(b); r.addLayout(col, 1); k = QPushButton(bt); k.clicked.connect(fn); r.addWidget(k)
            if n == 'Spotify': k2 = QPushButton('Import data export'); k2.clicked.connect(s.sp_files); r.addWidget(k2)
            v.addWidget(f)
        c = QLabel('Playback'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        s.chk = QCheckBox('Look up missing lyrics online (lrclib.net)'); s.chk.setChecked(s.cfg.get('lyrics_online', True)); s.chk.toggled.connect(lambda x: s.cfg.__setitem__('lyrics_online', x) or save_cfg(s.cfg)); v.addWidget(s.chk)
        v.addWidget(QLabel('Bounciness (lower = calmer)')); bs = ClickSlider(Qt.Horizontal); bs.setRange(0, 100); bs.setFixedWidth(260); bs.setValue(int((.5 - PH['C']) / .30 * 100)); bs.valueChanged.connect(s.bounce); v.addWidget(bs)
        s.add_bg(v)
        c = QLabel('Music folders'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c); s.fl = QLabel(); s.fl.setObjectName('dim'); s.fl.setWordWrap(True); v.addWidget(s.fl)
        b = QPushButton('Add folder'); b.clicked.connect(s.add_folder); v.addWidget(b, 0, Qt.AlignLeft); v.addStretch(); s.fl_upd(); sc.setWidget(w); return sc

if __name__ == '__main__':
    app = QApplication(sys.argv); app.setStyle('Fusion'); app.setFont(QFont('Segoe UI', 10)); app.setStyleSheet(QSS)
    pal = QPalette()
    for r, c in ((QPalette.Window, '#0a0a0a'), (QPalette.WindowText, '#fff'), (QPalette.Base, '#0d0d0d'), (QPalette.AlternateBase, '#161616'), (QPalette.Text, '#fff'),
                 (QPalette.Button, '#161616'), (QPalette.ButtonText, '#fff'), (QPalette.Highlight, ACC), (QPalette.HighlightedText, '#000')): pal.setColor(r, QColor(c))
    app.setPalette(pal)
    app.setWindowIcon(QIcon(asset('logo.png'))); B = Bridge(); w = Win(); w.show(); sys.exit(app.exec())
