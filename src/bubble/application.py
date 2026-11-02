"""Bubble Player - Spotify-style local music player (PySide6). No HTML: compiles to an exe with PyInstaller."""
import time, shutil, tempfile, subprocess, urllib.error, queue, sys, os, re, json, base64, hashlib, secrets, threading, urllib.request, urllib.parse, plistlib, webbrowser, random, datetime, struct, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QMediaDevices
try: from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat
except Exception: QAudioBufferOutput = QAudioFormat = None
try: from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception: QWebEngineView = None
try: import mutagen
except Exception: mutagen = None

PH = {'K': .10, 'C': .30}          # spring stiffness / damping (calmer than before)
ACC, DIM, TEXT = '#33d6e8', '#8c8c8c', '#f4f4f4'
HAND_CURSOR, PERFORMANCE_MODE = True, False
COV = {}; TH = {}                            # key -> QPixmap cache

from bubble.config import DATA_DIR, EXT, SONGS_DIR, create_windows_shortcuts, load_cfg, restore_cfg_backup, save_cfg
from bubble.services.importers import apple_import, deezer_import, fetch, resolve, spotdl_command, spotify_files, yt_import
from bubble.services.library import duplicate_groups, extras, parse_lrc, tag, write_lrc
from bubble.services.discord_presence import DiscordPresence
from bubble.services.plugin_host import load_plugins
from bubble.ui.audio_editor import AudioEditorDialog
from bubble.ui.plugin_manager import PluginManagerDialog
from bubble.ui.mini_player import MiniPlayerDialog

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

_QPB = QPushButton
class Pill(_QPB):
    """Every button in the app: a true pill (corner radius = half the height), drawn by hand so Qt styles can't square it off."""
    def __init__(s, *a): super().__init__(*a); s.setAttribute(Qt.WA_Hover); s.setCursor(Qt.PointingHandCursor if HAND_CURSOR else Qt.ArrowCursor)
    def sizeHint(s): h = super().sizeHint(); return QSize(h.width() + 6, max(h.height(), 38))
    def paintEvent(s, e):
        if s.objectName() in ('svcpill', 'flat'): return super().paintEvent(e)
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing); r = QRectF(s.rect()).adjusted(.5, .5, -.5, -.5); grey = s.objectName() == 'grey'
        base = QColor('#6f6f6f' if grey else '#ffffff')
        if not s.isEnabled(): base.setAlpha(110)
        elif s.isDown(): base = base.darker(130)
        elif s.underMouse(): base = QColor('#8a8a8a') if grey else QColor('#e4e4e4')
        p.setPen(Qt.NoPen); p.setBrush(base); p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(QFont('Segoe UI', 10, QFont.Bold)); p.setPen(QColor('#fff' if grey else '#000')); p.drawText(r, Qt.AlignCenter, s.text())
QPushButton = Pill

class ToggleSwitch(QCheckBox):
    """Small custom switch used by onboarding option rows."""
    def __init__(self, checked=False, parent=None):
        super().__init__(parent); self.setChecked(checked); self.setFixedSize(48, 26); self.setCursor(Qt.PointingHandCursor if HAND_CURSOR else Qt.ArrowCursor)
    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); track = QColor('#282333' if self.isChecked() else '#b8accd'); p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 1, 48, 24), 12, 12)
        x = 26 if self.isChecked() else 4; p.setBrush(QColor('#fff' if self.isChecked() else '#eeeaf4')); p.drawEllipse(QRectF(x, 5, 16, 16))

class WelcomeDialog(QDialog):
    """One-time onboarding carousel. AppData directories are created before it opens."""
    def __init__(self, cfg=None):
        super().__init__(); self.setWindowTitle('Welcome to Bubble'); self.setWindowIcon(QIcon(asset('logo.png')))
        self.cfg = cfg if cfg is not None else {}
        self.cfg.setdefault('bg', 'Black'); self.cfg.setdefault('accent_color', '#33d6e8'); self.cfg.setdefault('accent_intensity', 90)
        self.cfg.setdefault('show_local_files', True); self.cfg.setdefault('visualizer', True); self.cfg.setdefault('lyrics_online', True)
        self.cfg.setdefault('download_songs', False); self.cfg.setdefault('no_hand_cursor', False); self.cfg.setdefault('performance_mode', False)
        self.cfg.setdefault('desktop_shortcut', True); self.cfg.setdefault('start_menu_shortcut', True)
        self.setObjectName('WelcomeDialog'); self.setModal(True); self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint); self.setWindowState(Qt.WindowFullScreen); self.page = 0
        self.setStyleSheet('QDialog#WelcomeDialog{background:#8958ed;color:#171326} QLabel{color:#171326}')
        root = QVBoxLayout(self); root.setContentsMargins(24, 14, 24, 20); root.setSpacing(0)
        top = QHBoxLayout(); top.addStretch()
        self.skip = QPushButton('Skip'); self.skip.setObjectName('flat'); self.skip.setStyleSheet('QPushButton{background:#dfd5f2;color:#211b31;border:0;border-radius:18px;padding:8px 20px;font-weight:600} QPushButton:hover{background:#fff}'); self.skip.clicked.connect(self.finish); top.addWidget(self.skip)
        minimize = QPushButton('−'); minimize.setObjectName('flat'); minimize.setToolTip('Minimize'); minimize.setFixedSize(40, 40); minimize.setStyleSheet('QPushButton{background:#cdb9ee;color:#211b31;border:0;border-radius:20px;font-size:19px;font-weight:700} QPushButton:hover{background:#fff}'); minimize.clicked.connect(self.showMinimized); top.addWidget(minimize)
        close = QPushButton('X'); close.setObjectName('flat'); close.setToolTip('Close'); close.setFixedSize(40, 40); close.setStyleSheet('QPushButton{background:#dfd5f2;color:#211b31;border:0;border-radius:20px;font-size:15px;font-weight:700} QPushButton:hover{background:#fff}'); close.clicked.connect(self.reject); top.addWidget(close); root.addLayout(top)
        root.addStretch(1)
        center = QVBoxLayout(); center.setAlignment(Qt.AlignHCenter); center.setSpacing(8)
        mark = QLabel(); mark.setPixmap(QIcon(asset('logo.png')).pixmap(104, 104)); mark.setAlignment(Qt.AlignCenter); center.addWidget(mark, 0, Qt.AlignHCenter)
        brand = QLabel('Bubble'); brand.setAlignment(Qt.AlignCenter); brand.setStyleSheet('color:#fff;font-size:44px;font-weight:700;letter-spacing:-2px'); center.addWidget(brand)
        root.addLayout(center)
        root.addSpacing(14)
        screen = QApplication.primaryScreen(); screen_w = screen.availableGeometry().width() if screen else 1280
        self.card = QFrame(); self.card.setObjectName('welcomeCard'); self.card.setFixedWidth(min(660, max(440, int(screen_w * .76)))); self.card.setStyleSheet('QFrame#welcomeCard{background:#ded4ef;border-radius:22px}')
        card_col = QVBoxLayout(self.card); card_col.setContentsMargins(0, 0, 0, 0); card_col.setSpacing(5)
        slides = [('Welcome to Bubble.', 'Let’s get your music space ready.'), ('Choose your look', 'Pick a Bubble background and fine-tune your accent color.'), ('Make it yours', 'These preferences can be changed later in Settings.'), ('Add Bubble to your launcher', 'Choose shortcuts so Bubble is easy to find next time.')]
        self.pages = QStackedWidget(); self.pages.setMinimumHeight(64); card_col.addWidget(self.pages)
        for i, (heading, subtitle) in enumerate(slides):
            page = QWidget(); col = QVBoxLayout(page); col.setContentsMargins(26, 22, 26, 14); col.setSpacing(5)
            h = QLabel(heading); h.setStyleSheet('font-size:23px;font-weight:700'); col.addWidget(h)
            sub = QLabel(subtitle); sub.setWordWrap(True); sub.setStyleSheet('color:#514862;font-size:14px'); col.addWidget(sub)
            if i == 0:
                intro = QLabel('Play music from your library, download Spotify music with spotDL, and make listening feel like yours.\n\nBubble keeps songs under AppData and remembers your settings on this PC.'); intro.setWordWrap(True); intro.setStyleSheet('color:#514862;font-size:14px'); col.addWidget(intro)
            elif i == 1: self._theme_options(col)
            elif i == 2: self._preference_options(col)
            elif i == 3: self._launcher_options(col)
            self.pages.addWidget(page)
        controls = QFrame(); controls.setStyleSheet('QFrame{background:#d5c9e8;border-radius:0 0 22px 22px}')
        control_col = QHBoxLayout(controls); control_col.setContentsMargins(18, 10, 18, 12); control_col.setSpacing(8)
        self.back = QPushButton('←  Back'); self.back.setObjectName('flat'); self.back.setStyleSheet('QPushButton{background:transparent;color:#211b31;border:0;padding:9px 16px;font-weight:600} QPushButton:hover{background:#c5b4dd;border-radius:20px}'); self.back.clicked.connect(lambda: self.show_page(self.page - 1)); control_col.addWidget(self.back)
        control_col.addStretch()
        self.dots = QHBoxLayout(); self.dots.setSpacing(7); control_col.addLayout(self.dots)
        control_col.addStretch()
        self.dot_buttons = []
        for i in range(len(slides)):
            dot = QPushButton(''); dot.setObjectName('flat'); dot.setFixedSize(10, 10); dot.clicked.connect(lambda checked=False, n=i: self.show_page(n)); self.dot_buttons.append(dot); self.dots.addWidget(dot, 0, Qt.AlignCenter)
        self.next = QPushButton('Continue  →'); self.next.setStyleSheet('QPushButton{background:#fff;color:#211b31;border:0;border-radius:22px;padding:9px 20px;font-weight:600} QPushButton:hover{background:#f2eff9}'); self.next.clicked.connect(self.advance); control_col.addWidget(self.next)
        card_col.addWidget(controls); root.addWidget(self.card, 0, Qt.AlignHCenter)
        root.addStretch(1)
        self.show_page(0)
    def _theme_options(self, layout):
        grid = QGridLayout(); grid.setSpacing(9); self.theme_buttons = {}
        choices = [('Black', 'Dark'), ('Midnight', 'Midnight'), ('Plum', 'Plum'), ('Forest', 'Forest')]
        for n, (bgname, label) in enumerate(choices):
            bg, panel = next((b, p) for name, b, p in BGS if name == bgname)
            tile = QPushButton(f'  {label}'); tile.setObjectName('flat'); tile.setCheckable(True); tile.setFixedHeight(62); tile.clicked.connect(lambda checked=False, name=bgname: self.choose_theme(name)); self.theme_buttons[bgname] = tile
            tile.setStyleSheet(f'QPushButton{{background:{bg};color:#fff;border:3px solid {panel};border-radius:14px;text-align:left;padding-left:14px;font-weight:700}} QPushButton:checked{{border:3px solid {ACC}}} QPushButton:hover{{border:3px solid {ACC}}}')
            grid.addWidget(tile, n // 2, n % 2)
        layout.addLayout(grid)
        self.hue = QSlider(Qt.Horizontal); self.hue.setRange(0, 359); self.hue.setValue(QColor(self.cfg['accent_color']).hue() % 360); self.hue.valueChanged.connect(self.update_accent)
        self.hue.setStyleSheet('QSlider::groove:horizontal{height:12px;border-radius:6px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff5757,stop:0.17 #ffd34d,stop:0.34 #73e65c,stop:0.51 #39dfdc,stop:0.68 #586dff,stop:0.84 #c34bfa,stop:1 #ff5757)} QSlider::handle:horizontal{width:13px;height:18px;margin:-4px 0;background:#fff;border:2px solid #292333;border-radius:6px}')
        self.saturation = QSlider(Qt.Horizontal); self.saturation.setRange(25, 100); self.saturation.setValue(int(self.cfg.get('accent_intensity', 90))); self.saturation.valueChanged.connect(self.update_accent)
        self.accent_label = QLabel(); self.accent_label.setAlignment(Qt.AlignRight)
        self._slider_row(layout, 'Accent color', self.hue)
        self._slider_row(layout, 'Accent intensity', self.saturation, self.accent_label)
        self.choose_theme(self.cfg['bg']); self.update_accent()
    def _slider_row(self, layout, title, slider, value_label=None):
        row = QHBoxLayout(); name = QLabel(title); name.setStyleSheet('font-weight:600'); row.addWidget(name); row.addStretch()
        if value_label is not None: row.addWidget(value_label)
        layout.addLayout(row); layout.addWidget(slider)
    def choose_theme(self, name):
        self.cfg['bg'] = name
        for key_name, button in self.theme_buttons.items(): button.setChecked(key_name == name)
    def update_accent(self, *_):
        color = QColor.fromHsv(self.hue.value(), int(self.saturation.value() * 2.55), 230).name()
        self.cfg['accent_color'] = color; self.cfg['accent_intensity'] = self.saturation.value()
        if self.accent_label: self.accent_label.setText(color.upper()); self.accent_label.setStyleSheet(f'color:{color};font-weight:700')
    def _preference_options(self, layout):
        self.option_switches = {}
        options = [
            ('Local library', 'Show the My Files tab for music on your computer', 'show_local_files'),
            ('Offline downloads', 'Save supported imports under Bubble’s songs folder', 'download_songs'),
            ('Live visualizer', 'Show the audio spectrum while music plays', 'visualizer'),
            ('Online lyrics', 'Look up lyrics when a song has no saved lyrics', 'lyrics_online'),
            ('Normal arrow cursor', 'Use an arrow instead of the hand cursor on controls', 'no_hand_cursor'),
            ('Reduced animations', 'Limit decorative hover motion on slower computers', 'performance_mode'),
        ]
        for title, detail, key_name in options:
            row = QFrame(); row.setStyleSheet('QFrame{background:#d6cbe8;border-radius:10px} QLabel{color:#211b31}')
            line = QHBoxLayout(row); line.setContentsMargins(13, 4, 13, 4); line.setSpacing(10)
            text_col = QVBoxLayout(); text_col.setSpacing(1); a = QLabel(title); a.setStyleSheet('font-weight:700;font-size:12px'); b = QLabel(detail); b.setStyleSheet('color:#514862;font-size:10px'); text_col.addWidget(a); text_col.addWidget(b); line.addLayout(text_col, 1)
            switch = ToggleSwitch(bool(self.cfg.get(key_name, True if key_name in ('show_local_files', 'visualizer', 'lyrics_online') else False))); line.addWidget(switch); layout.addWidget(row); self.option_switches[key_name] = switch
    def _launcher_options(self, layout):
        app_row = QFrame(); app_row.setStyleSheet('QFrame{background:#d6cbe8;border-radius:10px} QLabel{color:#211b31}')
        line = QHBoxLayout(app_row); line.setContentsMargins(14, 10, 14, 10); icon = QLabel('♫'); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter); icon.setStyleSheet('background:#fff;border-radius:10px;font-size:23px;font-weight:700'); line.addWidget(icon)
        title_col = QVBoxLayout(); title_col.addWidget(QLabel('Bubble Player')); desc = QLabel('Your music player'); desc.setStyleSheet('color:#514862;font-size:11px'); title_col.addWidget(desc); line.addLayout(title_col); line.addStretch(); layout.addWidget(app_row)
        self.start_menu = self._shortcut_option(layout, 'Start Menu shortcut', 'Find Bubble by searching the Start Menu.', 'start_menu_shortcut')
        self.desktop = self._shortcut_option(layout, 'Desktop shortcut', 'Open Bubble directly from your desktop.', 'desktop_shortcut')
        paths = QLabel(f'Your files stay here:\nSongs: {SONGS_DIR}\nSettings: {DATA_DIR}'); paths.setWordWrap(True); paths.setTextInteractionFlags(Qt.TextSelectableByMouse); paths.setStyleSheet('color:#514862;font-size:11px;margin:4px 2px'); layout.addWidget(paths)
    def _shortcut_option(self, layout, title, detail, key_name):
        row = QFrame(); row.setStyleSheet('QFrame{background:#d6cbe8;border-radius:10px} QLabel{color:#211b31}')
        line = QHBoxLayout(row); line.setContentsMargins(13, 8, 13, 8); col = QVBoxLayout(); a = QLabel(title); a.setStyleSheet('font-weight:700;font-size:13px'); b = QLabel(detail); b.setStyleSheet('color:#514862;font-size:11px'); col.addWidget(a); col.addWidget(b); line.addLayout(col, 1)
        switch = ToggleSwitch(bool(self.cfg.get(key_name, True))); line.addWidget(switch); layout.addWidget(row); self.option_switches[key_name] = switch; return switch
    def show_page(self, n):
        self.page = max(0, min(n, self.pages.count() - 1)); self.pages.setCurrentIndex(self.page)
        current = self.pages.currentWidget(); current.ensurePolished(); current.layout().activate()
        self.pages.setFixedHeight(current.sizeHint().height())
        self.back.setEnabled(self.page > 0); self.next.setText('Finish setup  →' if self.page == self.pages.count() - 1 else 'Continue  →')
        for i, dot in enumerate(self.dot_buttons):
            dot.setStyleSheet(f'QPushButton{{border:0;border-radius:5px;background:{ACC if i == self.page else "#4a4a4a"};min-width:10px;max-width:10px;min-height:10px;max-height:10px;padding:0}}')
    def advance(self):
        if self.page == self.pages.count() - 1:
            self.finish()
        else: self.show_page(self.page + 1)
    def finish(self):
        for k, switch in self.option_switches.items(): self.cfg[k] = switch.isChecked()
        self.accept()

def fmt(ms):
    s = max(0, int(ms // 1000)); return f'{s // 60}:{s % 60:02d}'
def key(t): return t.get('_source_key') or t['path'] or t['url'] or t['title'] + t['artist']
def gen_cover(seed, n=400):
    h = int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) % 360; pm = QPixmap(n, n); p = QPainter(pm); g = QLinearGradient(0, 0, n, n)
    g.setColorAt(0, QColor.fromHsl(h, 35, 62)); g.setColorAt(1, QColor.fromHsl((h + 40) % 360, 35, 22))
    p.fillRect(0, 0, n, n, g); p.end(); return pm

def artwork_accent(pixmap):
    """Choose a vivid, common color from the cover instead of averaging it to gray."""
    if pixmap is None or pixmap.isNull(): return QColor('#33d6e8')
    image = pixmap.toImage().scaled(32, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    buckets = {}
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y).toHsv()
            if color.saturation() < 48 or color.value() < 35: continue
            hue_bin = (color.hue() // 18) % 20
            saturation_bin = min(3, color.saturation() // 64)
            buckets.setdefault((hue_bin, saturation_bin), []).append(color)
    if not buckets: return QColor('#33d6e8')
    # Prefer colors that occur often and have enough saturation to read as an accent.
    selected = max(buckets.values(), key=lambda colors: len(colors) * (1 + colors[0].saturation() / 510))
    hue = int(sum(color.hue() for color in selected) / len(selected))
    sat = max(150, int(sum(color.saturation() for color in selected) / len(selected)))
    value = max(170, min(225, int(sum(color.value() for color in selected) / len(selected))))
    return QColor.fromHsv(hue, min(255, sat), value)

class Bridge(QObject):
    imported = Signal(list); resolved = Signal(int, str, object); lyrics = Signal(int, str); status = Signal(str); cover = Signal(str, object); task_done = Signal(str); task_error = Signal(str, str); download_started = Signal(); duplicates = Signal(object); repaired = Signal(object)

# ---------------------------------------------------------------- tags, lyrics, streaming helpers








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
            out.append(dict(title=t['name'], artist=', '.join(a['name'] for a in t['artists']), album=t['album']['name'], dur=t['duration_ms'], path='', url=t.get('external_urls', {}).get('spotify', ''), src='Spotify', cover_url=im[0]['url'] if im else ''))
        url = j.get('next')
    B.imported.emit(out)
    mk = lambda t, tag: dict(title=t['name'], artist=', '.join(a['name'] for a in t['artists']), album=t['album']['name'], dur=t['duration_ms'], path='', url=t.get('external_urls', {}).get('spotify', ''), src='Spotify', cover_url=(t['album']['images'] or [{}])[0].get('url', ''), rec=tag)
    api = lambda u: fetch(u, hdr={'Authorization': 'Bearer ' + tok}); top = []
    try: top = api('https://api.spotify.com/v1/me/top/tracks?limit=30&time_range=medium_term')['items']; B.imported.emit([mk(t, 'top') for t in top])
    except Exception: pass
    try:
        mkt = api('https://api.spotify.com/v1/me').get('country', 'US'); have = {t['id'] for t in top}; recs = []
        for a in api('https://api.spotify.com/v1/me/top/artists?limit=6')['items']: recs += [mk(t, 'rec') for t in api(f"https://api.spotify.com/v1/artists/{a['id']}/top-tracks?market={mkt}")['tracks'][:5] if t['id'] not in have]
        B.imported.emit(recs)
    except Exception: pass
    B.status.emit(f'Spotify: {len(out)} liked songs imported'); return []



def sq(o, n):
    q = o.scaled(n, n, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation); return q.copy((q.width() - n) // 2, (q.height() - n) // 2, n, n)

def lines(p, x, yc, w, a, b, ca=None):
    """Two-line title/artist block, vertically centred on yc using real font metrics."""
    fa, fb = QFont('Segoe UI', 10, QFont.Bold), QFont('Segoe UI', 9); ma, mb = QFontMetrics(fa), QFontMetrics(fb); top = yc - (ma.height() + mb.height() + 2) / 2
    p.setFont(fa); p.setPen(QColor(ca or TEXT)); p.drawText(QPointF(x, top + ma.ascent()), ma.elidedText(a, Qt.ElideRight, int(w)))
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
    elif k == 'playlist': line((.18, .25), (.55, .25)); line((.18, .5), (.55, .5)); line((.18, .75), (.42, .75)); line((.7, .35), (.7, .78), (.86, .68))
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
        super().__init__(); s.setMouseTracking(True); s.setFocusPolicy(Qt.StrongFocus); s.pad = pad; s.st = [0., 0., 1., 0., 0., 0.]; s.hov = s.pressed = False; s.m = QPointF()
        s.tm = QTimer(s); s.tm.setInterval(16); s.tm.timeout.connect(s.step); s.setCursor(Qt.PointingHandCursor if HAND_CURSOR else Qt.ArrowCursor)
    def enterEvent(s, e): s.hov = True; s.tm.start() if not PERFORMANCE_MODE else s.update()
    def leaveEvent(s, e): s.hov = s.pressed = False; s.tm.start() if not PERFORMANCE_MODE else s.update()
    def mouseMoveEvent(s, e): s.m = e.position(); s.tm.start() if not PERFORMANCE_MODE else s.update()
    def mousePressEvent(s, e): s.pressed = True; s.tm.start() if not PERFORMANCE_MODE else s.update()
    def mouseReleaseEvent(s, e):
        if s.pressed and s.rect().contains(e.position().toPoint()): s.st[5] += .035; s.clicked.emit()
        s.pressed = False; s.tm.start() if not PERFORMANCE_MODE else s.update()
    def keyPressEvent(s, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter): s.clicked.emit(); e.accept(); return
        super().keyPressEvent(e)
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
        if s.hasFocus():
            p.resetTransform(); p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(ACC), 2, Qt.DashLine)); p.drawRoundedRect(QRectF(s.rect()).adjusted(2, 2, -2, -2), 6, 6)

class IconBtn(Springy):
    def __init__(s, kind, size=28, circle=False, pad=6):
        super().__init__(pad); s.kind, s.circle, s.on = kind, circle, False; s.setFixedSize(size + 2 * pad, size + 2 * pad); s.grow = .1
        labels = {'heart': 'Like current song', 'heartf': 'Unlike current song', 'folder': 'Library', 'clock': 'Recently played', 'playc': 'Play or pause', 'playlist': 'Playlists', 'library': 'Albums or library', 'gear': 'Settings', 'lyrics': 'Lyrics', 'sliders': 'Playback settings', 'shuffle': 'Shuffle', 'prev': 'Previous track', 'play': 'Play or pause', 'pause': 'Play or pause', 'next': 'Next track', 'repeat': 'Repeat mode', 'search': 'Search', 'close': 'Close', 'expand': 'Fullscreen', 'vol': 'Volume'}
        s.setAccessibleName(labels.get(kind, kind.replace('_', ' ').title()))
    def draw(s, p, r):
        if s.circle:
            bg = {'dark': QColor(0, 0, 0, 170), 'grey': QColor('#2a2a2a' if s.hov else '#1f1f1f'), 'green': QColor(ACC)}.get(s.circle, QColor('#fff')); p.setPen(Qt.NoPen); p.setBrush(bg); p.drawEllipse(r)
            icon_color = '#fff' if s.circle in ('dark', 'grey') else (TEXT if TEXT == '#17171b' else '#000')
            ic(p, s.kind, r.adjusted(r.width() * .27, r.width() * .27, -r.width() * .27, -r.width() * .27), QColor(icon_color))
        else:
            ic(p, s.kind, r, QColor(ACC if s.on else (TEXT if s.hov else DIM)))
            if s.on: p.setPen(Qt.NoPen); p.setBrush(QColor(ACC)); p.drawEllipse(QPointF(r.center().x(), r.bottom() + 4), 2, 2)

class Nav(Springy):
    def __init__(s, kind, text):
        super().__init__(4); s.kind, s.text, s.on, s.cnt = kind, text, False, ''; s.setAccessibleName(text); s.setFixedHeight(42); s.grow = .03; s.pull = .05
    def draw(s, p, r):
        pass
        col = QColor(TEXT if (s.on or s.hov) else DIM); cp = r.width() < 150; ic(p, s.kind, QRectF(r.center().x() - 11 if cp else r.x() + 14, r.center().y() - 11, 22, 22), col)
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
        p.setPen(QColor(TEXT)); p.setFont(QFont('Segoe UI', 10, QFont.Bold)); p.drawText(QPointF(x0, y0 + w + 24), p.fontMetrics().elidedText(s.t['title'], Qt.ElideRight, int(w)))
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
    def sizeHint(s, o, i): return QSize(0, 66 if s.w.stack.currentIndex() == 3 else 58)
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
        history_label = (i.data(Qt.UserRole + 1) or s.w.history_dates.get(k)) if s.w.stack.currentIndex() == 3 else None
        if history_label:
            w = max(80, w - 176); p.setFont(QFont('Segoe UI', 9)); p.setPen(QColor(DIM))
            p.drawText(QRectF(r.right() - 166, r.top(), 158, r.height()), Qt.AlignVCenter | Qt.AlignRight, history_label)
        lines(p, x, r.center().y(), w, t['title'], t['artist'], ACC if cur else '#fff'); p.restore()

class SeekBar(QWidget):
    """Time labels + progress bar painted as ONE widget so text and bar share an exact centre line."""
    sliderMoved = Signal(int)
    def __init__(s):
        super().__init__(); s.mn = s.mx = s.v = 0; s.lt = s.rt = '0:00'; s.down = s.hov = False; s.spectrum = []; s.setFocusPolicy(Qt.StrongFocus); s.setAccessibleName('Playback position'); s.setAccessibleDescription('Use left and right arrows to seek five seconds; hold Shift to seek 15 seconds. Home and End jump to the start and end.'); s.setFixedHeight(22); s.setMinimumWidth(220); s.setMouseTracking(True); s.setCursor(Qt.PointingHandCursor if HAND_CURSOR else Qt.ArrowCursor)
    def setRange(s, a, b): s.mn, s.mx = a, b; s.rt = fmt(b); s.update()
    def setValue(s, v):
        if not s.down: s.v = v; s.lt = fmt(v); s.update()
    def isSliderDown(s): return s.down
    def setSpectrum(s, levels): s.spectrum = list(levels or []); s.update()
    def _geo(s): return 54, s.width() - 54
    def _val(s, x): x0, x1 = s._geo(); return int(s.mn + (s.mx - s.mn) * max(0., min(1., (x - x0) / max(1, x1 - x0))))
    def enterEvent(s, e): s.hov = True; s.update()
    def leaveEvent(s, e): s.hov = False; s.update()
    def _drag(s, e): s.v = s._val(e.position().x()); s.lt = fmt(s.v); s.sliderMoved.emit(s.v); s.update()
    def mousePressEvent(s, e): s.down = True; s._drag(e)
    def mouseMoveEvent(s, e):
        if s.down: s._drag(e)
    def mouseReleaseEvent(s, e): s.down = False; s.update()
    def keyPressEvent(s, e):
        if e.key() in (Qt.Key_Left, Qt.Key_Down, Qt.Key_Right, Qt.Key_Up, Qt.Key_Home, Qt.Key_End):
            step = 15000 if e.modifiers() & Qt.ShiftModifier else 5000
            value = s.mn if e.key() == Qt.Key_Home else s.mx if e.key() == Qt.Key_End else s.v + (step if e.key() in (Qt.Key_Right, Qt.Key_Up) else -step)
            value = max(s.mn, min(s.mx, value)); s.setValue(value); s.sliderMoved.emit(value); e.accept(); return
        super().keyPressEvent(e)
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing); cy = s.height() / 2; x0, x1 = s._geo()
        f = QFont('Segoe UI', 9); p.setFont(f); fm = QFontMetricsF(f); base = cy + fm.capHeight() / 2; p.setPen(QColor(DIM))
        p.drawText(QPointF(x0 - 12 - fm.horizontalAdvance(s.lt), base), s.lt); p.drawText(QPointF(x1 + 12, base), s.rt)
        p.setPen(Qt.NoPen); p.setBrush(QColor('#4d4d4d')); p.drawRoundedRect(QRectF(x0, cy - 2, x1 - x0, 4), 2, 2)
        xx = x0 + (x1 - x0) * ((s.v - s.mn) / max(1, s.mx - s.mn)); on = s.hov or s.down
        p.setBrush(QColor(ACC if on else '#fff')); p.drawRoundedRect(QRectF(x0, cy - 2, max(0., xx - x0), 4), 2, 2)
        if s.spectrum:
            path = QPainterPath(); samples = max(2, min(72, len(s.spectrum) * 2))
            for i in range(samples):
                level = s.spectrum[min(len(s.spectrum) - 1, int(i * len(s.spectrum) / samples))]
                x = x0 + (x1 - x0) * i / (samples - 1); y = cy - (max(0, min(1, level)) - .1) * 10
                if i == 0: path.moveTo(x, y)
                else: path.lineTo(x, y)
            color = QColor(ACC); color.setAlpha(180); p.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.drawPath(path)
        if on: p.setBrush(QColor('#fff')); p.drawEllipse(QPointF(xx, cy), 6, 6)

class ClickSlider(QSlider):
    def __init__(s, *a): super().__init__(*a); s.setCursor(Qt.PointingHandCursor if HAND_CURSOR else Qt.ArrowCursor)
    def mousePressEvent(s, e):
        v = QStyle.sliderValueFromPosition(s.minimum(), s.maximum(), int(e.position().x()), s.width()); s.setValue(v); s.sliderMoved.emit(v); super().mousePressEvent(e)

class LyricsView(QWidget):
    def __init__(s):
        super().__init__(); s.setFocusPolicy(Qt.StrongFocus); s.setAccessibleName('Lyrics'); s.setAccessibleDescription('Use the arrow keys to scroll unsynchronized lyrics.'); s.lines = []; s.synced = False; s.cur = -1; s.off = 0.; s.scr = 0.; s.msg = 'No lyrics yet'
        s.tm = QTimer(s); s.tm.setInterval(16); s.tm.timeout.connect(s.step)
    big = False
    def line_heights(s):
        font = QFont('Segoe UI', 26 if s.big else 15, QFont.Bold if s.synced else QFont.DemiBold)
        metrics = QFontMetrics(font); width = max(80, s.width() - (36 if s.big else 24)); minimum = 92 if s.big else 46
        heights = []
        for _, text in s.lines:
            bounds = metrics.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, text)
            heights.append(max(minimum, bounds.height() + (22 if s.big else 12)))
        return heights
    def set(s, lines, synced, msg=''): s.lines, s.synced, s.msg, s.cur, s.off, s.scr = lines, synced, msg, -1, 0., 0.; s.update()
    def pos(s, ms):
        if not s.synced: return
        i = -1
        for n, (t, _) in enumerate(s.lines):
            if t <= ms + 120: i = n
            else: break
        if i != s.cur: s.cur = i; s.tm.start()
    def step(s):
        heights = s.line_heights(); idx = max(0, s.cur); tg = sum(heights[:idx]) + (heights[idx] / 2 if heights else 0)
        s.off += (tg - s.off) * .10; s.update()
        if abs(tg - s.off) < .5: s.off = tg; s.tm.stop()
    def resizeEvent(s, e):
        super().resizeEvent(e)
        if s.synced and s.lines: s.tm.start()
    def wheelEvent(s, e):
        if not s.synced: s.scr = max(0, min(s.scr - e.angleDelta().y() / 2, max(0, sum(s.line_heights()) - s.height() + 40))); s.update()
    def keyPressEvent(s, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown) and not s.synced:
            delta = 160 if e.key() in (Qt.Key_PageUp, Qt.Key_PageDown) else 40
            s.scr = max(0, min(s.scr + (delta if e.key() in (Qt.Key_Down, Qt.Key_PageDown) else -delta), max(0, sum(s.line_heights()) - s.height() + 40))); s.update(); e.accept(); return
        super().keyPressEvent(e)
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        f = QFont('Segoe UI', 26 if s.big else 15, QFont.Bold if s.synced else QFont.DemiBold); p.setFont(f)
        if not s.lines:
            message_color = QColor(TEXT); message_color.setAlpha(150); p.setPen(message_color); p.setFont(QFont('Segoe UI', 11)); p.drawText(s.rect().adjusted(14, 0, -14, 0), Qt.AlignCenter | Qt.TextWordWrap, s.msg); return
        heights = s.line_heights(); prefix = 0
        for i, (_, tx) in enumerate(s.lines):
            if s.synced:
                row_height = heights[i]; y = s.height() / 2 - s.off + prefix; d = i - s.cur
                if y < -row_height or y > s.height(): prefix += row_height; continue
                color = QColor(TEXT); color.setAlpha(255 if d == 0 else (110 if d > 0 else 70)); p.setPen(color)
                p.drawText(QRectF(12, y, s.width() - 24, row_height), Qt.AlignVCenter | (Qt.AlignHCenter if s.big else Qt.AlignLeft) | Qt.TextWordWrap, tx)
                prefix += row_height
            else:
                row_height = heights[i]; y = 16 - s.scr + prefix
                if y + row_height > 0 and y < s.height():
                    color = QColor(TEXT); color.setAlpha(215); p.setPen(color); p.drawText(QRectF(12, y, s.width() - 24, row_height), Qt.AlignVCenter | (Qt.AlignHCenter if s.big else Qt.AlignLeft) | Qt.TextWordWrap, tx)
                prefix += row_height
        if s.hasFocus():
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(ACC), 2, Qt.DashLine)); p.drawRoundedRect(QRectF(s.rect()).adjusted(2, 2, -2, -2), 8, 8)

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
QListWidget#albumList::item{padding:7px 12px;margin:3px 4px;border-radius:10px}
QListWidget#albumList::item:hover{background:#101010}
QListWidget#albumList::item:selected{background:#191919;color:#fff;border-left:3px solid #33d6e8}
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

def asset(name): return os.path.join(getattr(sys, '_MEIPASS', APP_ROOT), 'assets', name)
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
        if getattr(s, 'bgraw', None) is not None: s.set_frame(s.bgraw)
        if getattr(s, 'src', None): s.cur = s._mk(s.src); s.old = None

        p = QPainter(s); p.setRenderHint(QPainter.Antialiasing); pa = QPainterPath(); pa.addRoundedRect(QRectF(s.rect()).adjusted(.5, .5, -.5, -.5), 22, 22); p.setClipPath(pa); p.fillRect(s.rect(), s.base)
        for pm, op in ((s.old, 1.), (s.cur, s.a)):
            if pm: p.setOpacity(op); p.drawPixmap((s.width() - pm.width()) // 2, (s.height() - pm.height()) // 2, pm)
        overlay = QColor(255, 255, 255, 205 if s.cur else 0) if TEXT == '#17171b' else QColor(0, 0, 0, 150 if s.cur else 0)
        p.setOpacity(1); p.fillRect(s.rect(), overlay); p.setClipping(False); p.setPen(QPen(QColor('#d9d5e0' if TEXT == '#17171b' else '#1a1a1a'), 1)); p.setBrush(Qt.NoBrush); p.drawPath(pa)

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
        p.setPen(QColor(TEXT)); p.setFont(QFont('Segoe UI', 10, QFont.Bold)); p.drawText(QPointF(r.x(), r.y() + w + 24), p.fontMetrics().elidedText(s.ti, Qt.ElideRight, int(w)))
        p.setPen(QColor(DIM)); p.setFont(QFont('Segoe UI', 9)); p.drawText(QPointF(r.x(), r.y() + w + 43), p.fontMetrics().elidedText(s.su, Qt.ElideRight, int(w)))

class SongDelegate(QStyledItemDelegate):
    """Song rows: cover, title/artist, album, heart, duration - painted by hand."""
    def __init__(s, win): super().__init__(win); s.w = win; s.cur = -1
    def sizeHint(s, o, i): return QSize(0, 64)
    def paint(s, p, o, i):
        idx = i.data(Qt.UserRole); t = s.w.T[idx]; k = key(t); r = QRectF(o.rect); p.save(); p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        if o.state & QStyle.State_MouseOver: p.setPen(Qt.NoPen); p.setBrush(QColor('#eceaf1' if TEXT == '#17171b' else '#101010')); p.drawRoundedRect(r.adjusted(0, 2, 0, -2), 12, 12)
        pm = TH.get(k) or COV.get(k)
        if pm is None:
            if k not in GC: GC[k] = gen_cover(t['title'] + t['artist'], 64)
            pm = GC[k]
        c = QRectF(r.x() + 10, r.center().y() - 24, 48, 48); pa = QPainterPath(); pa.addRoundedRect(c, 8, 8); p.setClipPath(pa); p.drawPixmap(c, pm, QRectF(pm.rect())); p.setClipping(False)
        lines(p, c.right() + 14, r.center().y(), r.width() * .36, t['title'], t['artist'], ACC if idx == s.cur else TEXT)
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
QListWidget#albumList::item{padding:7px 12px;margin:3px 4px;border-radius:10px}
QListWidget#albumList::item:hover{background:#101010}
QListWidget#albumList::item:selected{background:#191919;color:#fff;border-left:3px solid #33d6e8}
QSlider::groove:horizontal{height:4px;background:#2c2c2c;border-radius:2px} QSlider::sub-page:horizontal{background:#fff;border-radius:2px} QSlider::sub-page:horizontal:hover{background:#33d6e8}
QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;border-radius:6px;background:#fff}
QScrollArea{background:transparent;border:none} QScrollBar:vertical{background:transparent;width:8px} QScrollBar::handle:vertical{background:#262626;border-radius:4px;min-height:30px}
QScrollBar::add-line,QScrollBar::sub-line{height:0}
"""

QSS_BASE = QSS
def apply_runtime_preferences(cfg, app):
    global ACC, DIM, TEXT, HAND_CURSOR, PERFORMANCE_MODE, QSS
    color = QColor(cfg.get('accent_color', '#33d6e8'))
    ACC = color.name() if color.isValid() else '#33d6e8'
    light = cfg.get('app_theme', 'Dark') == 'Light'
    TEXT = '#17171b' if light else '#f4f4f4'
    DIM = '#4e4e57' if light else ('#f0f0f0' if cfg.get('high_contrast', False) else '#8c8c8c')
    QSS = QSS_BASE.replace('#33d6e8', ACC)
    if cfg.get('high_contrast', False): QSS = QSS.replace('#b3b3b3', '#f2f2f2').replace('#9a9a9a', '#f2f2f2')
    bg, panel = next(((base, surface) for name, base, surface in BGS if name == cfg.get('bg', 'Black')), ('#000000', '#070707'))
    rail_bg = 'rgba(0,0,0,70)' if cfg.get('bg_media') else bg
    QSS = QSS.replace('#rail,#bar{background:#000', f'#rail,#bar{{background:{rail_bg}').replace('#070707', panel).replace('#0a0a0a', panel).replace('#0b0b0b', panel)
    if light:
        QSS += '''
QWidget{color:#17171b}
QLabel{color:#17171b}
QLabel#dim{color:#4e4e57}
#rail,#bar{background:#f1eff7;border-color:#e6e2ef}
#rpanel{background:#f5f3fa;border-color:#e2deeb}
#panel,QFrame#svc,#banner{background:#f1eff7;border:1px solid #e2deeb}
#hotbar{background:rgba(255,255,255,200)}
QLineEdit,QPlainTextEdit,#topsearch{background:#fff;color:#17171b;border:1px solid #d9d5e0;selection-background-color:#c9b8f2}
QLineEdit:hover,#topsearch:hover{background:#faf9fc}
QLineEdit:focus,#topsearch:focus{border-color:#6c4ab6}
QPushButton#flat{color:#4e4e57}
QPushButton#flat:hover{background:#e4e0ec;color:#17171b}
QPushButton#chip{background:#e8e4ef;color:#17171b}
QPushButton#chip:checked{background:#d7c8f5;color:#251447}
QPushButton#svcpill{color:#282731}
QPushButton#svcpill:hover{background:#e4e0ec}
QCheckBox{color:#17171b}
QListWidget,QTableWidget{color:#17171b;selection-background-color:#ddd3f1;selection-color:#17171b}
QListWidget#albumList::item:hover{background:#eeebf4}
QListWidget#albumList::item:selected{background:#e7e1f1;color:#17171b;border-left:3px solid #6c4ab6}
QComboBox{background:#fff;color:#17171b;border:1px solid #d9d5e0;padding:6px;border-radius:7px}
QSlider::groove:horizontal{background:#d5d1dc}
QSlider::sub-page:horizontal{background:#6c4ab6}
QSlider::handle:horizontal{background:#6c4ab6}
QScrollBar::handle:vertical{background:#c8c3d1}
'''
    else:
        QSS = QSS.replace('#rail,#bar{background:rgba(0,0,0,70)', f'#rail,#bar{{background:{rail_bg}')
    custom_qss = cfg.get('custom_qss', '')
    if isinstance(custom_qss, str): QSS += '\n' + custom_qss[:24000]
    HAND_CURSOR = not bool(cfg.get('no_hand_cursor', False))
    PERFORMANCE_MODE = bool(cfg.get('performance_mode', False))
    app.setStyleSheet(QSS)
    pal = app.palette()
    palette = ((QPalette.Window, '#faf9fc'), (QPalette.WindowText, TEXT), (QPalette.Base, '#ffffff'), (QPalette.AlternateBase, '#f1eff7'), (QPalette.Text, TEXT), (QPalette.Button, '#f1eff7'), (QPalette.ButtonText, TEXT), (QPalette.Highlight, '#d7c8f5'), (QPalette.HighlightedText, '#251447')) if light else ((QPalette.Window, bg), (QPalette.WindowText, '#fff'), (QPalette.Base, panel), (QPalette.AlternateBase, '#161616'), (QPalette.Text, '#fff'), (QPalette.Button, '#161616'), (QPalette.ButtonText, '#fff'), (QPalette.Highlight, ACC), (QPalette.HighlightedText, '#000'))
    for role, value in palette: pal.setColor(role, QColor(value))
    app.setPalette(pal)

class SpectrumMeter(QWidget):
    """Compact live frequency visualizer fed from QMediaPlayer's decoded audio tap."""
    def __init__(s):
        super().__init__(); s.levels = [0.02] * 28; s.setMinimumHeight(42); s.setMaximumHeight(48); s.setMinimumWidth(120)
        s.timer = QTimer(s); s.timer.setInterval(40); s.timer.timeout.connect(s.decay); s.timer.start()
    def feed(s, samples, sample_rate):
        if not samples: return
        source_count = len(samples); n = 256; effective_rate = sample_rate * n / max(n, source_count)
        if len(samples) < n: samples = samples + [0.0] * (n - len(samples))
        else: samples = [samples[int(i * len(samples) / n)] for i in range(n)]
        windowed = [x * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) for i, x in enumerate(samples)]
        nyquist = max(1, effective_rate / 2); max_freq = max(60, min(12000, nyquist)); bands = []
        for band in range(len(s.levels)):
            low_hz = 55 * (max_freq / 55) ** (band / len(s.levels)); high_hz = 55 * (max_freq / 55) ** ((band + 1) / len(s.levels))
            center_hz = min(nyquist * .98, math.sqrt(low_hz * high_hz)); coeff = 2 * math.cos(2 * math.pi * center_hz / effective_rate)
            q1 = q2 = 0.0
            for sample in windowed:
                q0 = sample + coeff * q1 - q2; q2, q1 = q1, q0
            power = max(0.0, q1 * q1 + q2 * q2 - coeff * q1 * q2)
            bands.append(min(1.0, math.sqrt(power) / n * 18))
        s.levels = [max(value, old * .72) for value, old in zip(bands, s.levels)]; s.update()
    def decay(s):
        s.levels = [max(.015, x * .94) for x in s.levels]; s.update()
    def paintEvent(s, event):
        p = QPainter(s); p.setRenderHint(QPainter.Antialiasing); p.fillRect(s.rect(), Qt.transparent)
        mode = getattr(s, 'mode', 'Bars')
        if mode == 'Dots':
            gap = s.width() / len(s.levels); radius = max(2.0, min(5.0, gap * .24)); cy = s.height() / 2
            p.setPen(Qt.NoPen)
            for i, level in enumerate(s.levels):
                color = QColor('#33d6e8'); color.setAlpha(100 + int(155 * min(1, level)))
                p.setBrush(color); p.drawEllipse(QPointF((i + .5) * gap, cy), radius, radius + level * 7)
            return
        gap = 3; bw = max(2, (s.width() - gap * (len(s.levels) - 1)) / len(s.levels)); base = s.height()
        for i, level in enumerate(s.levels):
            h = max(3, (base - 3) * level); x = i * (bw + gap)
            g = QLinearGradient(x, base - h, x, base); g.setColorAt(0, QColor('#33d6e8')); g.setColorAt(1, QColor('#5751b8'))
            p.setPen(Qt.NoPen); p.setBrush(g)
            if mode == 'Mirror':
                mid = base / 2; half = max(2, (base * .46) * level)
                p.drawRoundedRect(QRectF(x, mid - half, bw, half * 2), bw / 2, bw / 2)
            else: p.drawRoundedRect(QRectF(x, base - h, bw, h), bw / 2, bw / 2)

class Win(QWidget):
    def __init__(s):
        super().__init__(); s.setWindowTitle('Bubble'); s.setWindowIcon(QIcon(asset('logo.png'))); s.resize(1340, 830); s.setMinimumSize(760, 560)
        pal = s.palette(); pal.setColor(QPalette.Window, QColor('#000')); s.setPalette(pal); s.setAutoFillBackground(True)
        s.cfg = load_cfg(); s.cfg.setdefault('folders', []); s.history_dates = {}
        if not isinstance(s.cfg.get('play_history'), list): s.cfg['play_history'] = []
        saved_history = s.cfg.get('play_history', [])
        for event in saved_history:
            if not isinstance(event, dict) or not event.get('key') or not event.get('played_at') or event['key'] in s.history_dates: continue
            try:
                stamp = datetime.datetime.fromisoformat(event['played_at']).astimezone()
                s.history_dates[event['key']] = stamp.strftime('%b ') + str(stamp.day) + stamp.strftime(', %Y  %I:%M %p')
            except Exception: s.history_dates[event['key']] = str(event['played_at'])
        s.discord = None
        s.plugins = load_plugins()
        if not isinstance(s.cfg.get('playlists'), list): s.cfg['playlists'] = []
        s.cfg['playlists'] = [p for p in s.cfg['playlists'] if isinstance(p, dict) and isinstance(p.get('name'), str) and isinstance(p.get('tracks'), list)]
        if SONGS_DIR not in s.cfg['folders']: s.cfg['folders'].insert(0, SONGS_DIR); save_cfg(s.cfg)
        s.T = []; s.keys = set(); s.i = -1; s.play_order = None; s.play_source_order = None; s.queue_keys = s.cfg.get('queue', []); s.queue_keys = list(s.queue_keys) if isinstance(s.queue_keys, list) else []; s.current_playlist = -1; s.shuf = False; s.rep = 0; s.cols = 6; s.loading = set(); s.cards = []; s.homekeys = set(); s.lists = []; s.full = False; s.bgmedia = False; s.mv = s.vp = s.bgpm = s.bgraw = None; s.vt = 0; s.dim = s.cfg.get('bg_dim', .55); s.download_cancel = threading.Event(); s.download_proc = None; s.download_count = 0
        s.ratings = s.cfg.setdefault('ratings', {}); s.sleep_timer = QTimer(s); s.sleep_timer.setSingleShot(True); s.sleep_timer.timeout.connect(s.sleep_now)
        s.fade_timer = QTimer(s); s.fade_timer.setInterval(40); s.fade_timer.timeout.connect(s.fade_tick); s.fade_state = None
        s.liked = set(s.cfg.get('liked', [])); s.cq = queue.Queue(); threading.Thread(target=cover_worker, args=(s.cq,), daemon=True).start(); s.dg = SongDelegate(s)
        s.pl = QMediaPlayer(s); s.ao = QAudioOutput(s); s.pl.setAudioOutput(s.ao); s.ao.setVolume(max(0, min(100, int(s.cfg.get('volume', 80)))) / 100); s.pl.setPlaybackRate(float(s.cfg.get('playback_speed', 100)) / 100); PH['C'] = s.cfg.get('damp', .30)
        saved_device = s.cfg.get('audio_device', '')
        if saved_device:
            for device in QMediaDevices.audioOutputs():
                if bytes(device.id()).decode('utf-8', 'ignore') == saved_device: s.ao.setDevice(device); break
        s.audio_tap = None
        if QAudioBufferOutput:
            try:
                s.audio_tap = QAudioBufferOutput(s); s.pl.setAudioBufferOutput(s.audio_tap); s.audio_tap.audioBufferReceived.connect(s.on_audio_buffer)
            except Exception: s.audio_tap = None
        s.hdeb = QTimer(s); s.hdeb.setSingleShot(True); s.hdeb.setInterval(400); s.hdeb.timeout.connect(s.home_refresh)
        root = QVBoxLayout(s); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0); body = QHBoxLayout(); body.setSpacing(0); root.addLayout(body, 1)
        s.railw = s.mk_rail(); body.addWidget(s.railw); s.midw = QWidget(); mid = QVBoxLayout(s.midw); mid.setContentsMargins(0, 0, 0, 0); mid.setSpacing(0); s.topbar = QWidget(); s.topbar.setLayout(s.mk_top()); mid.addWidget(s.topbar); s.stack = QStackedWidget(); mid.addWidget(s.stack, 1); body.addWidget(s.midw, 1)
        for pg in (s.mk_home(), s.mk_songs('Library', True), s.mk_songs('Liked songs'), s.mk_songs('Recently played'), s.mk_settings(), s.mk_youtube(), s.mk_playlists(), s.mk_albums(), s.mk_artists()): s.stack.addWidget(pg)
        s.rpanel = s.mk_rpanel(); body.addWidget(s.rpanel); s.barw = s.mk_bar(); root.addWidget(s.barw)
        s.yt_full = False; s.yt_was_fullscreen = False; s.yt_was_maximized = False; s.rp_user_hidden = False
        B.imported.connect(s.add_tracks); B.cover.connect(s.on_cover); B.resolved.connect(s.on_resolved); B.lyrics.connect(s.on_lyrics); B.status.connect(lambda m: s.note.setText(m)); B.task_done.connect(s.on_task_done); B.task_error.connect(s.on_task_error); B.download_started.connect(s.on_download_started); B.duplicates.connect(s.show_duplicate_groups); B.repaired.connect(s.finish_repair)
        s.pl.positionChanged.connect(s.on_pos); s.pl.durationChanged.connect(lambda d: s.seek.setRange(0, d))
        s.pl.mediaStatusChanged.connect(lambda m: s.step(1, auto=True) if m == QMediaPlayer.MediaStatus.EndOfMedia else None)
        s.pl.playbackStateChanged.connect(lambda _: s.bplay.__setattr__('kind', 'pause' if s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState else 'play') or s.bplay.update())
        s.pl.playbackStateChanged.connect(lambda _: s.update_discord_presence())
        s.pl.playbackStateChanged.connect(lambda _: s.update_mini_player())
        s.bind_shortcuts()
        if s.cfg.get('discord_presence') and s.cfg.get('discord_client_id'):
            s.discord = DiscordPresence(s.cfg['discord_client_id'])
        s.set_media(s.cfg.get('bg_media') or '', False); s.go(0); s.add_tracks(s.cfg.get('remote', []), save=False)
        s.setWindowOpacity(max(60, min(100, int(s.cfg.get('window_opacity', 100)))) / 100)
        if s.cfg.get('layout_preset') == 'Compact': s.rpanel.hide()
        elif s.cfg.get('layout_preset') == 'Wide': s.resize(1560, 900)
        fl = s.cfg.get('folders', [])
        if fl: threading.Thread(target=s.scan, args=(fl,), daemon=True).start()

    # ---- frame
    def mk_rail(s):
        r = QFrame(); r.setObjectName('rail'); r.setFixedWidth(76); v = QVBoxLayout(r); v.setContentsMargins(0, 14, 0, 14); v.setSpacing(6); s.rail = {}
        lg = LogoBtn(); lg.clicked.connect(lambda: s.go(0)); v.addWidget(lg, 0, Qt.AlignHCenter); v.addSpacing(20)
        for k, pg in (('heart', 2), ('folder', 1), ('clock', 3)):
            b = IconBtn(k, 26, False, 9); b.setAccessibleName({2: 'Liked songs', 1: 'Library', 3: 'Play history'}[pg]); b.clicked.connect(lambda pg=pg: s.go(pg)); s.rail[pg] = b; v.addWidget(b, 0, Qt.AlignHCenter)
        yt = IconBtn('playc', 26, False, 9); yt.setToolTip('YouTube'); yt.setAccessibleName('Open YouTube player'); yt.clicked.connect(lambda: s.go(5)); s.rail[5] = yt; v.addWidget(yt, 0, Qt.AlignHCenter)
        pl = IconBtn('playlist', 26, False, 9); pl.setToolTip('Playlists'); pl.setAccessibleName('Playlists'); pl.clicked.connect(lambda: s.go(6)); s.rail[6] = pl; v.addWidget(pl, 0, Qt.AlignHCenter)
        albums = IconBtn('library', 26, False, 9); albums.setToolTip('Albums'); albums.setAccessibleName('Albums'); albums.clicked.connect(lambda: s.go(7)); s.rail[7] = albums; v.addWidget(albums, 0, Qt.AlignHCenter)
        artists = IconBtn('heart', 26, False, 9); artists.setToolTip('Artists'); artists.setAccessibleName('Artists'); artists.clicked.connect(lambda: s.go(8)); s.rail[8] = artists; v.addWidget(artists, 0, Qt.AlignHCenter)
        v.addSpacing(12)
        for k, f in (('sliders', lambda: s.go(4)), ('lyrics', lambda: s.toggle_rp())):
            b = IconBtn(k, 40, 'grey', 4); b.clicked.connect(f); v.addWidget(b, 0, Qt.AlignHCenter)
        if not s.cfg.get('show_local_files', True): s.rail[1].hide()
        for page in (1, 2, 3, 5, 6, 7, 8):
            if not s.cfg.get('sidebar_sections', {}).get(str(page), True): s.rail[page].hide()
        v.addStretch(); g = IconBtn('gear', 26, False, 9); g.clicked.connect(lambda: s.go(4)); s.rail[4] = g; v.addWidget(g, 0, Qt.AlignHCenter); return r
    def mk_top(s):
        h = QHBoxLayout(); h.setContentsMargins(24, 14, 24, 6); h.setSpacing(6); h.addStretch(1)
        s.q = QLineEdit(); s.q.setObjectName('topsearch'); s.q.setPlaceholderText('Search tracks, artists, or albums...'); s.q.setMinimumWidth(220); s.q.setMaximumWidth(520); s.q.setFixedHeight(44); s.q.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        s.q.addAction(QIcon(glyph('search', 22, '#b3b3b3')), QLineEdit.LeadingPosition); s.q.textChanged.connect(s.on_search); h.addWidget(s.q); h.addStretch(1)
        s.service_buttons = []
        for name, k in (('YouTube', 'yt'), ('YouTube Music', 'ytm'), ('SoundCloud', 'sc')):
            b = QPushButton(' ' + name); b.setObjectName('svcpill'); b.setIcon(QIcon(svc_icon(k, 18))); b.setIconSize(QSize(18, 18)); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: s.link(n)); h.addWidget(b); s.service_buttons.append(b)
        return h
    def mk_rpanel(s):
        f = RPanel(); f.setObjectName('rpanel'); f.setFixedWidth(310); s.rp = f; v = QVBoxLayout(f); v.setContentsMargins(16, 12, 16, 16); v.setSpacing(12)
        hr = QHBoxLayout(); t = QLabel('Now playing'); t.setObjectName('dim'); hr.addStretch(); hr.addWidget(t); x = IconBtn('close', 14, False, 6); x.clicked.connect(s.toggle_rp); hr.addWidget(x); v.addLayout(hr)
        s.rcov = Cov(240, 18, .03, 8); s.rcov.set(ph_pix()); v.addWidget(s.rcov, 0, Qt.AlignHCenter)
        s.rt = QLabel('No track playing'); s.rt.setStyleSheet('font-size:17px;font-weight:700'); s.rt.setAlignment(Qt.AlignCenter); s.rt.setWordWrap(True)
        s.ra = QLabel('Select a track to listen'); s.ra.setObjectName('dim'); s.ra.setAlignment(Qt.AlignCenter); v.addWidget(s.rt); v.addWidget(s.ra)
        s.visualizer = SpectrumMeter(); s.visualizer.setVisible(s.cfg.get('visualizer', True)); v.addWidget(s.visualizer)
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
        R = QHBoxLayout(); R.addStretch(); s.queue_button = QPushButton('Queue 0'); s.queue_button.setObjectName('flat'); s.queue_button.clicked.connect(s.show_queue); s.sleep_button = QPushButton('Sleep'); s.sleep_button.setObjectName('flat'); s.sleep_button.clicked.connect(s.set_sleep_timer); s.mini_button = QPushButton('Mini'); s.mini_button.setObjectName('flat'); s.mini_button.clicked.connect(s.open_mini_player)
        ly = IconBtn('lyrics', 20); ly.clicked.connect(s.toggle_rp); vi = IconBtn('vol', 20); s.vol = ClickSlider(Qt.Horizontal); s.vol.setRange(0, 100); s.vol.setValue(int(s.cfg.get('volume', 80))); s.vol.setFixedWidth(110)
        s.vol.valueChanged.connect(s.set_volume); R.addWidget(s.queue_button); R.addWidget(s.sleep_button); R.addWidget(s.mini_button); R.addWidget(ly); R.addWidget(vi); R.addWidget(s.vol); rw = QWidget(); rw.setLayout(R); h.addWidget(rw, 3); return bar

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
        tx = QVBoxLayout(); tx.setSpacing(2); t1 = QLabel('Download Spotify music with spotDL'); t1.setStyleSheet('font-size:16px;font-weight:700'); t2 = QLabel('Paste a track, album, or playlist link in Settings'); t2.setObjectName('dim')
        tx.addWidget(t1); tx.addWidget(t2); b.addLayout(tx); b.addStretch(); ib = QPushButton('Open downloader'); ib.setObjectName('grey'); ib.clicked.connect(lambda: s.go(4)); b.addWidget(ib)
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
    def mk_youtube(s):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(22, 14, 22, 18)
        s.yttoolbar = QWidget(); bar = QHBoxLayout(s.yttoolbar); title = QLabel('YouTube'); title.setObjectName('h1'); bar.addWidget(title); bar.addStretch()
        back = QPushButton('Back'); reload = QPushButton('Reload'); bar.addWidget(back); bar.addWidget(reload); v.addWidget(s.yttoolbar)
        if QWebEngineView:
            s.ytview = QWebEngineView(); s.ytview.setUrl(QUrl('https://www.youtube.com/')); v.addWidget(s.ytview, 1)
            s.ytview.page().fullScreenRequested.connect(s.youtube_fullscreen_request)
            back.clicked.connect(s.ytview.back); reload.clicked.connect(s.ytview.reload)
        else:
            s.ytview = None; msg = QLabel('Embedded YouTube needs PySide6-WebEngine. Install it with: pip install PySide6-WebEngine'); msg.setObjectName('dim'); msg.setAlignment(Qt.AlignCenter); v.addWidget(msg, 1)
            back.setEnabled(False); reload.setEnabled(False)
        return page
    def youtube_fullscreen_request(s, request):
        request.accept()
        if request.toggleOn():
            if s.yt_full: return
            s.yt_was_fullscreen = s.isFullScreen(); s.yt_was_maximized = s.isMaximized(); s.yt_full = True
            s.railw.hide(); s.topbar.hide(); s.yttoolbar.hide(); s.rpanel.hide(); s.barw.hide()
            s.showFullScreen(); s.ytview.setFocus()
        else: s.exit_youtube_fullscreen()
    def exit_youtube_fullscreen(s):
        if not s.yt_full: return
        s.yt_full = False
        s.railw.show(); s.topbar.show(); s.yttoolbar.show(); s.rpanel.show(); s.barw.show()
        if s.yt_was_fullscreen: s.showFullScreen()
        elif s.yt_was_maximized: s.showMaximized()
        else: s.showNormal()
    def mk_songs(s, title, lib=False):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(48, 10, 24, 12); v.setSpacing(10); r = QHBoxLayout(); t = QLabel(title); t.setObjectName('h1'); r.addWidget(t); r.addStretch()
        if lib:
            s.library_source = QComboBox(); s.library_source.addItems(['All sources', 'Local', 'Spotify', 'YouTube', 'YouTube Music', 'SoundCloud', 'Deezer', 'Apple Music']); s.library_source.currentIndexChanged.connect(lambda _: s.apply_library_filter()); r.addWidget(s.library_source)
            s.library_sort = QComboBox(); s.library_sort.addItems(['Recently added', 'Title', 'Artist', 'Album', 'Top rated']); s.library_sort.currentIndexChanged.connect(lambda _: s.refresh_library_list()); r.addWidget(s.library_sort)
            b = QPushButton('Import folder'); b.setObjectName('grey'); b.clicked.connect(s.add_folder); r.addWidget(b)
        v.addLayout(r)
        if lib:
            filters = QHBoxLayout(); s.filter_artist = QLineEdit(); s.filter_artist.setPlaceholderText('Filter artist'); s.filter_artist.textChanged.connect(lambda _: s.apply_library_filter()); filters.addWidget(s.filter_artist)
            s.filter_album = QLineEdit(); s.filter_album.setPlaceholderText('Filter album'); s.filter_album.textChanged.connect(lambda _: s.apply_library_filter()); filters.addWidget(s.filter_album)
            s.filter_year = QComboBox(); s.filter_year.addItem('Any year'); s.filter_year.currentIndexChanged.connect(lambda _: s.apply_library_filter()); filters.addWidget(s.filter_year)
            s.filter_duration = QComboBox(); s.filter_duration.addItems(['Any length', 'Under 3 min', '3–5 min', 'Over 5 min']); s.filter_duration.currentIndexChanged.connect(lambda _: s.apply_library_filter()); filters.addWidget(s.filter_duration)
            clear_filters = QPushButton('Clear filters'); clear_filters.setObjectName('flat'); clear_filters.clicked.connect(s.clear_library_filters); filters.addWidget(clear_filters); v.addLayout(filters)
            tools = QHBoxLayout(); add_queue = QPushButton('Add selected to queue'); add_queue.clicked.connect(lambda: s.queue_selection(s.lists[0])); tools.addWidget(add_queue)
            remove = QPushButton('Remove selected'); remove.setObjectName('grey'); remove.clicked.connect(lambda: s.remove_selected_tracks(s.lists[0])); tools.addWidget(remove)
            addpl = QPushButton('Add to playlist'); addpl.setObjectName('grey'); addpl.clicked.connect(lambda: s.add_selected_to_playlist(s.lists[0])); tools.addWidget(addpl); tools.addStretch(); v.addLayout(tools)
            edit_tags = QPushButton('Edit tags'); edit_tags.setObjectName('grey'); edit_tags.clicked.connect(lambda: s.bulk_edit_tags(s.lists[0])); tools.insertWidget(tools.count() - 1, edit_tags)
        l = QListWidget(); l.setFrameShape(QFrame.NoFrame); l.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); l.setMouseTracking(True); l.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); l.setItemDelegate(s.dg); l.setSelectionMode(QAbstractItemView.ExtendedSelection)
        l.setContextMenuPolicy(Qt.CustomContextMenu); l.customContextMenuRequested.connect(lambda pos, view=l: s.track_context_menu(view, pos))
        l.itemDoubleClicked.connect(lambda it: s.play(it.data(Qt.UserRole))); v.addWidget(l, 1); s.lists.append(l); return w
    def mk_albums(s):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(48, 18, 28, 22)
        title = QLabel('Albums'); title.setObjectName('h1'); v.addWidget(title)
        note = QLabel('Browse albums in your local and downloaded library. Double-click an album to play it.'); note.setObjectName('dim'); v.addWidget(note)
        s.album_list = QListWidget(); s.album_list.setObjectName('albumList'); s.album_list.setIconSize(QSize(42, 42)); s.album_list.itemDoubleClicked.connect(s.play_album); v.addWidget(s.album_list, 1); return page
    def mk_artists(s):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(48, 18, 28, 22)
        title = QLabel('Artists'); title.setObjectName('h1'); v.addWidget(title)
        note = QLabel('Browse artists represented in your library. Double-click an artist to play their songs.'); note.setObjectName('dim'); v.addWidget(note)
        s.artist_list = QListWidget(); s.artist_list.itemDoubleClicked.connect(s.play_artist); v.addWidget(s.artist_list, 1); return page
    def refresh_browse_pages(s):
        if not hasattr(s, 'album_list'): return
        albums = {}; artists = {}
        for i, track in enumerate(s.T):
            if track.get('rec'): continue
            artist = track.get('artist') or 'Unknown artist'; album = track.get('album') or 'Unknown album'
            albums.setdefault((artist, album), []).append(i); artists.setdefault(artist, []).append(i)
        s.album_list.clear()
        for (artist, album), indices in sorted(albums.items(), key=lambda pair: (pair[0][0].casefold(), pair[0][1].casefold())):
            count = len(indices); item = QListWidgetItem(f'{album}  ·  {artist}  ·  {count} track' + ('' if count == 1 else 's')); item.setData(Qt.UserRole, indices)
            cover = next((COV.get(key(s.T[index])) or TH.get(key(s.T[index])) for index in indices if COV.get(key(s.T[index])) or TH.get(key(s.T[index]))), None)
            if cover: item.setIcon(QIcon(cover.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item.setSizeHint(QSize(0, 62)); s.album_list.addItem(item)
        s.artist_list.clear()
        for artist, indices in sorted(artists.items(), key=lambda pair: pair[0].casefold()):
            item = QListWidgetItem(f'{artist}  ·  {len(indices)} tracks'); item.setData(Qt.UserRole, indices); s.artist_list.addItem(item)
    def play_group(s, item):
        order = item.data(Qt.UserRole) or []
        if not order: return
        s.play_source_order = list(order); s.play_order = list(order)
        if s.shuf: random.shuffle(s.play_order)
        s.play(s.play_order[0], keep_order=True)
    def play_album(s, item): s.play_group(item)
    def play_artist(s, item): s.play_group(item)
    def mk_playlists(s):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(48, 18, 28, 22); v.setSpacing(12)
        header = QHBoxLayout(); title = QLabel('Your playlists'); title.setObjectName('h1'); header.addWidget(title); header.addStretch()
        smart = QPushButton('+ Smart playlist'); smart.setObjectName('grey'); smart.clicked.connect(lambda: s.create_playlist(True)); header.addWidget(smart)
        create = QPushButton('+ New playlist'); create.clicked.connect(s.create_playlist); header.addWidget(create); v.addLayout(header)
        tools = QHBoxLayout(); s.playlist_combo = QComboBox(); s.playlist_combo.setMinimumWidth(240); s.playlist_combo.currentIndexChanged.connect(s.select_playlist); tools.addWidget(s.playlist_combo)
        rename = QPushButton('Rename'); rename.setObjectName('grey'); rename.clicked.connect(s.rename_playlist); tools.addWidget(rename)
        delete = QPushButton('Delete'); delete.setObjectName('grey'); delete.clicked.connect(s.delete_playlist); tools.addWidget(delete)
        export = QPushButton('Export M3U'); export.setObjectName('grey'); export.clicked.connect(s.export_playlist_m3u); tools.addWidget(export)
        import_m3u = QPushButton('Import M3U'); import_m3u.setObjectName('grey'); import_m3u.clicked.connect(s.import_playlist_m3u); tools.addWidget(import_m3u); tools.addStretch(); v.addLayout(tools)
        s.playlist_hint = QLabel('Create a playlist to collect songs for a mood, activity, or album.'); s.playlist_hint.setObjectName('dim'); v.addWidget(s.playlist_hint)
        s.playlist_tracks = QListWidget(); s.playlist_tracks.setFrameShape(QFrame.NoFrame); s.playlist_tracks.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); s.playlist_tracks.setMouseTracking(True); s.playlist_tracks.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); s.playlist_tracks.setItemDelegate(s.dg); s.playlist_tracks.itemDoubleClicked.connect(s.play_playlist_item); v.addWidget(s.playlist_tracks, 1); s.lists.append(s.playlist_tracks)
        actions = QHBoxLayout(); add = QPushButton('Add songs'); add.clicked.connect(s.add_to_playlist); actions.addWidget(add)
        current = QPushButton('Add current song'); current.setObjectName('grey'); current.clicked.connect(s.add_current_to_playlist); actions.addWidget(current)
        remove = QPushButton('Remove selected'); remove.setObjectName('grey'); remove.clicked.connect(s.remove_from_playlist); actions.addWidget(remove)
        actions.addStretch(); play = QPushButton('Play playlist'); play.clicked.connect(s.play_playlist); actions.addWidget(play); v.addLayout(actions)
        s.refresh_playlist_menu(); return page
    def refresh_playlist_menu(s, *_):
        combo = getattr(s, 'playlist_combo', None)
        if combo is None: return
        old = s.current_playlist; combo.blockSignals(True); combo.clear()
        for playlist in s.cfg['playlists']: combo.addItem(playlist['name'])
        s.current_playlist = min(old, combo.count() - 1) if combo.count() else -1; combo.setCurrentIndex(s.current_playlist); combo.blockSignals(False); s.refresh_playlist_tracks()
    def select_playlist(s, index): s.current_playlist = index; s.refresh_playlist_tracks()
    def refresh_playlist_tracks(s):
        if not hasattr(s, 'playlist_tracks'): return
        l = s.playlist_tracks; l.clear()
        playlists = s.cfg.get('playlists', []); p = playlists[s.current_playlist] if 0 <= s.current_playlist < len(playlists) else None
        if not p:
            s.playlist_hint.setText('Create a playlist to collect songs for a mood, activity, or album.'); return
        indices = s.playlist_indices(p)
        for i in indices: it = QListWidgetItem(); it.setData(Qt.UserRole, i); l.addItem(it)
        waiting = max(0, len(p.get('tracks', [])) - len(indices)) if not p.get('smart') else 0
        s.playlist_hint.setText(f'{len(indices)} songs' + (' · Smart rules update automatically' if p.get('smart') else (f' · {waiting} will appear as the library loads' if waiting else '')))
    def save_playlist_changes(s): save_cfg(s.cfg); s.refresh_playlist_menu()
    def playlist_indices(s, playlist):
        by_key = {key(track): i for i, track in enumerate(s.T)}
        if playlist.get('smart'):
            rule = playlist['smart']; query = rule.get('query', '').casefold(); source = rule.get('source', 'All sources'); minimum = int(rule.get('min_rating', 0))
            return [i for i, track in enumerate(s.T) if not track.get('rec') and
                    (source == 'All sources' or track.get('src', 'Local') == source) and
                    (not query or query in ' '.join(str(track.get(k, '')) for k in ('title', 'artist', 'album')).casefold()) and
                    int(s.ratings.get(key(track), 0)) >= minimum]
        return [by_key[k] for k in playlist.get('tracks', []) if k in by_key]
    def create_playlist(s, smart=False):
        name, ok = QInputDialog.getText(s, 'New playlist', 'Playlist name:')
        name = name.strip()
        if not ok or not name: return
        if any(p['name'].casefold() == name.casefold() for p in s.cfg['playlists']): QMessageBox.information(s, 'Playlist exists', 'Choose a different playlist name.'); return
        playlist = {'name': name, 'tracks': []}
        if smart:
            editor = QDialog(s); editor.setWindowTitle('Smart playlist rules'); form = QFormLayout(editor)
            query = QLineEdit(); query.setPlaceholderText('Optional title, artist, or album text'); form.addRow('Match text', query)
            source = QComboBox(); source.addItems(['All sources', 'Local', 'Spotify', 'YouTube', 'YouTube Music', 'SoundCloud', 'Apple Music']); form.addRow('Source', source)
            rating = QSpinBox(); rating.setRange(0, 5); rating.setPrefix('At least '); rating.setSuffix(' stars'); form.addRow('Rating', rating)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(editor.accept); buttons.rejected.connect(editor.reject); form.addRow(buttons)
            if editor.exec() != QDialog.Accepted: return
            playlist['smart'] = {'query': query.text().strip(), 'source': source.currentText(), 'min_rating': rating.value()}
        s.cfg['playlists'].append(playlist); s.current_playlist = len(s.cfg['playlists']) - 1; s.save_playlist_changes(); s.playlist_combo.setCurrentIndex(s.current_playlist)
    def rename_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        old = s.cfg['playlists'][s.current_playlist]['name']; name, ok = QInputDialog.getText(s, 'Rename playlist', 'Playlist name:', text=old); name = name.strip()
        if not ok or not name: return
        if any(i != s.current_playlist and p['name'].casefold() == name.casefold() for i, p in enumerate(s.cfg['playlists'])): QMessageBox.information(s, 'Playlist exists', 'Choose a different playlist name.'); return
        s.cfg['playlists'][s.current_playlist]['name'] = name; s.save_playlist_changes()
    def delete_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        name = s.cfg['playlists'][s.current_playlist]['name']
        if QMessageBox.question(s, 'Delete playlist', f'Delete “{name}”? The songs themselves will stay in your library.') != QMessageBox.Yes: return
        del s.cfg['playlists'][s.current_playlist]; s.current_playlist = min(s.current_playlist, len(s.cfg['playlists']) - 1); s.save_playlist_changes()
    def add_to_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])):
            QMessageBox.information(s, 'Choose a playlist', 'Create or select a playlist first.'); return
        if s.cfg['playlists'][s.current_playlist].get('smart'):
            QMessageBox.information(s, 'Smart playlist', 'Edit the smart rules instead of adding tracks manually.'); return
        d = QDialog(s); d.setWindowTitle('Add songs'); d.resize(520, 600); v = QVBoxLayout(d)
        search = QLineEdit(); search.setPlaceholderText('Filter your library...'); v.addWidget(search)
        l = QListWidget(); l.setSelectionMode(QAbstractItemView.MultiSelection)
        for t in s.T:
            if t.get('rec'): continue
            item = QListWidgetItem(f"{t['title']}   ·   {t['artist']}"); item.setData(Qt.UserRole, key(t)); l.addItem(item)
        search.textChanged.connect(lambda q: [l.item(i).setHidden(bool(q) and q.casefold() not in l.item(i).text().casefold()) for i in range(l.count())]); v.addWidget(l, 1)
        row = QHBoxLayout(); row.addStretch(); cancel = QPushButton('Cancel'); cancel.setObjectName('grey'); add = QPushButton('Add selected'); row.addWidget(cancel); row.addWidget(add); v.addLayout(row); cancel.clicked.connect(d.reject); add.clicked.connect(d.accept)
        if not d.exec(): return
        target = s.cfg['playlists'][s.current_playlist]; known = set(target['tracks']); target['tracks'].extend(i.data(Qt.UserRole) for i in l.selectedItems() if i.data(Qt.UserRole) not in known); s.save_playlist_changes()
    def add_current_to_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])) or s.i < 0: return
        if s.cfg['playlists'][s.current_playlist].get('smart'): return
        tracks = s.cfg['playlists'][s.current_playlist]['tracks']; k = key(s.T[s.i])
        if k not in tracks: tracks.append(k); s.save_playlist_changes()
    def export_playlist_m3u(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        playlist = s.cfg['playlists'][s.current_playlist]
        path, _ = QFileDialog.getSaveFileName(s, 'Export playlist', playlist['name'] + '.m3u8', 'M3U playlists (*.m3u *.m3u8)')
        if not path: return
        tracks = [s.T[i] for i in s.playlist_indices(playlist)]
        with open(path, 'w', encoding='utf-8') as output:
            output.write('#EXTM3U\n')
            for track in tracks:
                location = track.get('path') or track.get('url')
                if not location: continue
                output.write(f"#EXTINF:{max(0, int(track.get('dur', 0) / 1000))},{track.get('artist', 'Unknown artist')} - {track.get('title', 'Unknown')}\n{location}\n")
        B.status.emit(f"Exported {len(tracks)} tracks to {os.path.basename(path)}")
    def import_playlist_m3u(s):
        path, _ = QFileDialog.getOpenFileName(s, 'Import playlist', '', 'M3U playlists (*.m3u *.m3u8)')
        if not path: return
        name = os.path.splitext(os.path.basename(path))[0]; tracks = []; pending_title = ''
        try:
            with open(path, encoding='utf-8-sig', errors='replace') as source:
                for raw in source:
                    line = raw.strip()
                    if not line: continue
                    if line.startswith('#EXTINF:'):
                        pending_title = line.split(',', 1)[1] if ',' in line else ''
                        continue
                    if line.startswith('#'): continue
                    location = line if '://' in line else os.path.normpath(os.path.join(os.path.dirname(path), line))
                    if os.path.isfile(location):
                        track = tag(location)
                        if track['artist'] == 'Unknown artist' and pending_title:
                            parts = pending_title.rsplit(' - ', 1)
                            if len(parts) == 2: track['artist'], track['title'] = parts
                    elif '://' in location:
                        parts = pending_title.rsplit(' - ', 1)
                        track = dict(title=parts[-1] if parts else pending_title or location, artist=parts[0] if len(parts) == 2 else 'Unknown artist', album=name, dur=0, path='', url=location, src='Playlist', cover_url='')
                    else:
                        pending_title = ''; continue
                    tracks.append(track); pending_title = ''
        except OSError as exc:
            QMessageBox.warning(s, 'Playlist import failed', str(exc)); return
        if not tracks:
            QMessageBox.information(s, 'Empty playlist', 'No playable entries were found in that M3U file.'); return
        if any(p['name'].casefold() == name.casefold() for p in s.cfg['playlists']): name += ' (imported)'
        s.cfg['remote'].extend(track for track in tracks if track['src'] != 'Local' or track['path'] not in {t.get('path') for t in s.T})
        s.add_tracks(tracks, save=False)
        s.cfg['playlists'].append({'name': name, 'tracks': [key(track) for track in tracks]}); s.current_playlist = len(s.cfg['playlists']) - 1; s.save_playlist_changes()
        B.status.emit(f'Imported {len(tracks)} tracks from {os.path.basename(path)}')
    def remove_from_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        if s.cfg['playlists'][s.current_playlist].get('smart'):
            QMessageBox.information(s, 'Smart playlist', 'Edit the smart rules to change its contents.'); return
        selected = {key(s.T[item.data(Qt.UserRole)]) for item in s.playlist_tracks.selectedItems()}
        if selected: s.cfg['playlists'][s.current_playlist]['tracks'] = [k for k in s.cfg['playlists'][s.current_playlist]['tracks'] if k not in selected]; s.save_playlist_changes()
    def play_playlist(s):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        order = s.playlist_indices(s.cfg['playlists'][s.current_playlist])
        if not order: B.status.emit('This playlist has no songs available yet'); return
        s.play_source_order = list(order)
        if s.shuf: random.shuffle(order)
        s.play_order = order; s.play(order[0], keep_order=True)
    def play_playlist_item(s, item):
        if not (0 <= s.current_playlist < len(s.cfg['playlists'])): return
        order = s.playlist_indices(s.cfg['playlists'][s.current_playlist])
        if item.data(Qt.UserRole) in order: s.play_source_order = list(order); s.play_order = order; s.play(item.data(Qt.UserRole), keep_order=True)
    def fill(s, l, idxs):
        l.clear()
        for n in idxs:
            it = QListWidgetItem(); it.setData(Qt.UserRole, n)
            if len(s.lists) > 2 and l is s.lists[2]:
                track_key = key(s.T[n]); it.setToolTip('Last played: ' + s.history_dates.get(track_key, 'date not recorded for older history'))
            l.addItem(it)
    def fill_play_history(s):
        view = s.lists[2]; view.clear(); by_key = {key(track): index for index, track in enumerate(s.T)}
        events = s.cfg.get('play_history', [])
        if not events:
            s.fill(view, [by_key[k] for k in s.cfg.get('recent', []) if k in by_key]); return
        for event in events:
            if not isinstance(event, dict): continue
            index = by_key.get(event.get('key'))
            if index is None: continue
            raw = event.get('played_at', '')
            try:
                stamp = datetime.datetime.fromisoformat(raw).astimezone(); label = stamp.strftime('%b ') + str(stamp.day) + stamp.strftime(', %Y  %I:%M %p')
            except Exception: label = str(raw) or 'date not recorded'
            item = QListWidgetItem(); item.setData(Qt.UserRole, index); item.setData(Qt.UserRole + 1, label); item.setToolTip('Played: ' + label); view.addItem(item)
    def go(s, n):
        s.stack.setCurrentIndex(n)
        if n == 2: s.fill(s.lists[1], [i for i, t in enumerate(s.T) if key(t) in s.liked])
        if n == 3: s.fill_play_history()
        if n == 6: s.refresh_playlist_menu()
        if n in (7, 8): s.refresh_browse_pages()
        for pg, b in s.rail.items(): b.on = pg == n; b.update()
    def on_search(s, txt):
        s.search_text = txt.casefold(); s.apply_library_filter()
        if txt and s.stack.currentIndex() != 1: s.go(1)
    def apply_library_filter(s):
        if not s.lists: return
        q = getattr(s, 'search_text', s.q.text() if hasattr(s, 'q') else '').casefold()
        source = s.library_source.currentText() if hasattr(s, 'library_source') else 'All sources'
        artist_query = s.filter_artist.text().casefold() if hasattr(s, 'filter_artist') else ''
        album_query = s.filter_album.text().casefold() if hasattr(s, 'filter_album') else ''
        year_query = s.filter_year.currentText() if hasattr(s, 'filter_year') else 'Any year'
        duration_mode = s.filter_duration.currentText() if hasattr(s, 'filter_duration') else 'Any length'
        l = s.lists[0]
        for row in range(l.count()):
            item = l.item(row); track = s.T[item.data(Qt.UserRole)]
            haystack = ' '.join(str(track.get(k, '')) for k in ('title', 'artist', 'album', 'src')).casefold()
            source_ok = source == 'All sources' or track.get('src', 'Local') == source
            duration = int(track.get('dur') or 0); duration_ok = (duration_mode == 'Any length' or (duration_mode == 'Under 3 min' and 0 < duration < 180000) or (duration_mode == '3–5 min' and 180000 <= duration <= 300000) or (duration_mode == 'Over 5 min' and duration > 300000))
            item.setHidden((bool(q) and q not in haystack) or not source_ok or artist_query not in str(track.get('artist', '')).casefold() or album_query not in str(track.get('album', '')).casefold() or (year_query != 'Any year' and str(track.get('year') or '') != year_query) or not duration_ok)
    def clear_library_filters(s):
        s.filter_artist.clear(); s.filter_album.clear(); s.filter_year.setCurrentIndex(0); s.filter_duration.setCurrentIndex(0); s.library_source.setCurrentIndex(0); s.q.clear()
    def refresh_filter_options(s):
        if not hasattr(s, 'filter_year'): return
        previous = s.filter_year.currentText(); years = sorted({str(track.get('year')) for track in s.T if str(track.get('year') or '').isdigit()}, reverse=True)
        s.filter_year.blockSignals(True); s.filter_year.clear(); s.filter_year.addItem('Any year'); s.filter_year.addItems(years); s.filter_year.setCurrentText(previous if previous in years else 'Any year'); s.filter_year.blockSignals(False)
    def refresh_library_list(s):
        if not s.lists: return
        s.refresh_filter_options()
        sort_mode = s.library_sort.currentText() if hasattr(s, 'library_sort') else 'Recently added'
        indices = [i for i, track in enumerate(s.T) if not track.get('rec')]
        if sort_mode == 'Title': indices.sort(key=lambda i: (s.T[i].get('title') or '').casefold())
        elif sort_mode == 'Artist': indices.sort(key=lambda i: (s.T[i].get('artist') or '').casefold())
        elif sort_mode == 'Album': indices.sort(key=lambda i: (s.T[i].get('album') or '').casefold())
        elif sort_mode == 'Top rated': indices.sort(key=lambda i: (-int(s.ratings.get(key(s.T[i]), 0)), (s.T[i].get('title') or '').casefold()))
        s.fill(s.lists[0], indices); s.apply_library_filter()
    def selected_track_indices(s, view):
        return list(dict.fromkeys(item.data(Qt.UserRole) for item in view.selectedItems() if item.data(Qt.UserRole) is not None))
    def queue_selection(s, view):
        selected = s.selected_track_indices(view)
        if not selected and view.currentItem(): selected = [view.currentItem().data(Qt.UserRole)]
        for index in selected:
            if 0 <= index < len(s.T): s.queue_keys.append(key(s.T[index]))
        s.cfg['queue'] = s.queue_keys; save_cfg(s.cfg); s.update_queue_button()
        B.status.emit(f'Added {len(selected)} song(s) to the queue')
    def update_queue_button(s):
        if hasattr(s, 'queue_button'): s.queue_button.setText(f'Queue {len(s.queue_keys)}')
    def open_mini_player(s):
        if s.i < 0:
            QMessageBox.information(s, 'Mini Player', 'Start a song first, then open Mini Player.'); return
        if not getattr(s, 'mini_window', None):
            s.mini_window = MiniPlayerDialog(); s.mini_window.play_pause.connect(s.toggle); s.mini_window.previous.connect(lambda: s.step(-1)); s.mini_window.next.connect(lambda: s.step(1)); s.mini_window.restore.connect(s.restore_main_window); s.mini_window.finished.connect(s.mini_window_closed)
        s.update_mini_player(); s.hide(); s.mini_window.show(); s.mini_window.raise_()
    def update_mini_player(s):
        if getattr(s, 'mini_window', None) and 0 <= s.i < len(s.T):
            track = s.T[s.i]; s.mini_window.set_track(track.get('title'), track.get('artist'), COV.get(key(track)), s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
    def restore_main_window(s):
        if getattr(s, 'mini_window', None): s.mini_window.hide()
        s.showNormal(); s.raise_(); s.activateWindow()
    def mini_window_closed(s, *_):
        if not s.isVisible(): s.restore_main_window()
    def show_queue(s):
        dlg = QDialog(s); dlg.setWindowTitle('Up next'); dlg.resize(520, 520); layout = QVBoxLayout(dlg)
        view = QListWidget(); view.setSelectionMode(QAbstractItemView.SingleSelection); view.setDragDropMode(QAbstractItemView.InternalMove); view.setDefaultDropAction(Qt.MoveAction); view.setDragDropOverwriteMode(False); layout.addWidget(view, 1)
        def save_order(*_):
            s.queue_keys = [view.item(row).data(Qt.UserRole) for row in range(view.count())]
            s.cfg['queue'] = s.queue_keys; save_cfg(s.cfg); s.update_queue_button()
        def refill():
            view.clear()
            by_key = {key(track): track for track in s.T}
            for track_key in s.queue_keys:
                track = by_key.get(track_key)
                if track:
                    item = QListWidgetItem(f"{track.get('title', 'Unknown')}  ·  {track.get('artist', 'Unknown artist')}"); item.setData(Qt.UserRole, track_key); view.addItem(item)
            s.update_queue_button()
        def move(delta):
            row = view.currentRow(); target = row + delta
            if not (0 <= row < view.count() and 0 <= target < view.count()): return
            item = view.takeItem(row); view.insertItem(target, item); view.setCurrentRow(target); save_order()
        def remove():
            row = view.currentRow()
            if 0 <= row < view.count(): view.takeItem(row); save_order()
        def play_item(item):
            track_key = item.data(Qt.UserRole); index = next((i for i, track in enumerate(s.T) if key(track) == track_key), -1)
            if index >= 0:
                s.queue_keys = [k for k in s.queue_keys if k != track_key]; s.cfg['queue'] = s.queue_keys; save_cfg(s.cfg); s.play(index); refill()
        view.itemDoubleClicked.connect(play_item)
        view.model().rowsMoved.connect(save_order)
        row = QHBoxLayout()
        for label, callback in (('Move up', lambda: move(-1)), ('Move down', lambda: move(1)), ('Remove', remove)):
            button = QPushButton(label); button.setObjectName('grey'); button.clicked.connect(callback); row.addWidget(button)
        clear = QPushButton('Clear queue'); clear.clicked.connect(lambda: (view.clear(), save_order())); row.addWidget(clear)
        done = QPushButton('Done'); done.clicked.connect(dlg.accept); row.addWidget(done); layout.addLayout(row); refill(); dlg.exec()
    def rate_track(s, index):
        if not (0 <= index < len(s.T)): return
        track_key = key(s.T[index]); value, ok = QInputDialog.getInt(s, 'Rate song', f"Rating for {s.T[index].get('title', 'song')} (0 clears rating):", int(s.ratings.get(track_key, 0)), 0, 5)
        if ok:
            if value: s.ratings[track_key] = value
            else: s.ratings.pop(track_key, None)
            s.cfg['ratings'] = s.ratings; save_cfg(s.cfg); s.refresh_library_list()
    def open_audio_editor(s, index):
        if not (0 <= index < len(s.T)) or not s.T[index].get('path') or not os.path.isfile(s.T[index]['path']):
            QMessageBox.information(s, 'Audio editor', 'Choose a local audio file to trim or process.'); return
        track = s.T[index]; source = track['path']; suffix = os.path.splitext(source)[1]
        default = os.path.join(SONGS_DIR, os.path.splitext(os.path.basename(source))[0] + '_edited' + suffix)
        output, _ = QFileDialog.getSaveFileName(s, 'Save edited copy', default, 'Audio files (*' + suffix + ')')
        if not output: return
        editor = AudioEditorDialog(source, output, track.get('dur', 0), s); editor.rendered.connect(s.audio_rendered); s.audio_editor = editor; editor.show()
    def audio_rendered(s, path):
        track = tag(path); track['src'] = 'Local'; s.add_tracks([track]); B.status.emit(f"Edited copy added: {track['title']}")
    def run_plugin_action(s, callback, index):
        try: callback(dict(s.T[index]), s)
        except Exception as exc: QMessageBox.warning(s, 'Plugin action failed', str(exc))
    def manage_plugins(s):
        PluginManagerDialog(s).exec(); s.plugins = load_plugins(); B.status.emit(f'{len(s.plugins.actions)} plugin action(s) loaded')
    def track_context_menu(s, view, position):
        item = view.itemAt(position)
        if not item: return
        if not item.isSelected(): view.setCurrentItem(item)
        indices = s.selected_track_indices(view) or [item.data(Qt.UserRole)]
        menu = QMenu(view); add_queue = menu.addAction('Add to queue'); add_playlist = menu.addAction('Add to playlist')
        rate = menu.addAction('Rate song'); remove = menu.addAction('Remove from Bubble library')
        menu.addSeparator(); edit = menu.addAction('Trim / edit audio…'); edit.setEnabled(bool(s.T[indices[0]].get('path')))
        plugin_menu = menu.addMenu('Plugins') if s.plugins.actions else None; plugin_actions = {}
        if plugin_menu:
            for label, callback in s.plugins.actions: plugin_actions[plugin_menu.addAction(label)] = callback
        action = menu.exec(view.mapToGlobal(position))
        if action is add_queue: s.queue_selection(view)
        elif action is add_playlist: s.add_selected_to_playlist(view)
        elif action is rate: s.rate_track(indices[0])
        elif action is remove: s.remove_selected_tracks(view)
        elif action is edit: s.open_audio_editor(indices[0])
        elif action in plugin_actions: s.run_plugin_action(plugin_actions[action], indices[0])
    def add_selected_to_playlist(s, view):
        indices = s.selected_track_indices(view)
        if not indices and view.currentItem(): indices = [view.currentItem().data(Qt.UserRole)]
        if not indices: return
        playlists = s.cfg.get('playlists', [])
        if not playlists:
            s.create_playlist(); playlists = s.cfg.get('playlists', [])
        if not playlists: return
        names = [p['name'] for p in playlists]; name, ok = QInputDialog.getItem(s, 'Add to playlist', 'Playlist:', names, 0, False)
        if ok:
            target = next(p for p in playlists if p['name'] == name); target.setdefault('tracks', [])
            for index in indices:
                if 0 <= index < len(s.T) and key(s.T[index]) not in target['tracks']: target['tracks'].append(key(s.T[index]))
            s.save_playlist_changes()
    def remove_selected_tracks(s, view):
        indices = s.selected_track_indices(view)
        if not indices and view.currentItem(): indices = [view.currentItem().data(Qt.UserRole)]
        tracks = [s.T[i] for i in indices if 0 <= i < len(s.T)]
        if not tracks or QMessageBox.question(s, 'Remove from library', f'Remove {len(tracks)} selected song(s) from Bubble? Audio files will stay on disk.') != QMessageBox.Yes: return
        removed = {key(track) for track in tracks}; current_key = key(s.T[s.i]) if 0 <= s.i < len(s.T) else None
        if current_key in removed:
            s.pl.stop(); s.pl.setSource(QUrl()); s.i = -1; s.bt.setText('No track playing'); s.ba.setText('Select a track to listen')
        for track_key in removed:
            s.cfg.get('lyrics', {}).pop(track_key, None); s.ratings.pop(track_key, None); COV.pop(track_key, None); TH.pop(track_key, None); GC.pop(track_key, None)
        s.T = [track for track in s.T if key(track) not in removed]; s.keys = {key(track) for track in s.T}
        s.cfg['remote'] = [track for track in s.cfg.get('remote', []) if key(track) not in removed]
        s.liked.difference_update(removed); s.cfg['liked'] = sorted(s.liked); s.cfg['recent'] = [k for k in s.cfg.get('recent', []) if k not in removed]
        s.cfg['play_history'] = [event for event in s.cfg.get('play_history', []) if not isinstance(event, dict) or event.get('key') not in removed]
        for track_key in removed: s.history_dates.pop(track_key, None)
        s.cfg['ratings'] = s.ratings; s.cfg['playlists'] = [{**playlist, 'tracks': [k for k in playlist.get('tracks', []) if k not in removed]} for playlist in s.cfg.get('playlists', [])]
        s.queue_keys = [k for k in s.queue_keys if k not in removed]; s.cfg['queue'] = s.queue_keys
        s.play_order = s.play_source_order = None; s.i = next((i for i, track in enumerate(s.T) if key(track) == current_key), -1); save_cfg(s.cfg)
        for list_view in s.lists[1:]: list_view.clear()
        s.refresh_library_list(); s.go(s.stack.currentIndex()); s.refresh_playlist_tracks(); s.home_refresh(); s.update_queue_button(); B.status.emit(f'Removed {len(removed)} song(s) from Bubble')
    def bulk_edit_tags(s, view):
        indices = s.selected_track_indices(view)
        if not indices and view.currentItem(): indices = [view.currentItem().data(Qt.UserRole)]
        indices = [i for i in indices if 0 <= i < len(s.T)]
        if not indices: B.status.emit('Select one or more library tracks first'); return
        dialog = QDialog(s); dialog.setWindowTitle(f'Edit tags for {len(indices)} tracks'); dialog.resize(440, 260); layout = QVBoxLayout(dialog)
        note = QLabel('Set a shared value on every selected track. Leave a field blank to keep its current value. Local files also receive embedded tag updates where supported.'); note.setWordWrap(True); note.setObjectName('dim'); layout.addWidget(note)
        fields = {}
        form = QFormLayout()
        for field, label in (('artist', 'Artist'), ('album', 'Album'), ('genre', 'Genre'), ('year', 'Year')):
            entry = QLineEdit(); entry.setPlaceholderText('Leave unchanged'); form.addRow(label, entry); fields[field] = entry
        layout.addLayout(form); buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok); buttons.button(QDialogButtonBox.Ok).setText('Apply'); buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept); layout.addWidget(buttons)
        if not dialog.exec(): return
        values = {field: entry.text().strip() for field, entry in fields.items() if entry.text().strip()}
        if not values: return
        failed = 0; updated_keys = set()
        for index in indices:
            track = s.T[index]; updated_keys.add(key(track))
            for field, value in values.items(): track[field] = value
            if track.get('path') and mutagen:
                try:
                    audio = mutagen.File(track['path'], easy=True)
                    if audio is not None:
                        for field, value in values.items(): audio['date' if field == 'year' else field] = [value]
                        audio.save()
                except Exception: failed += 1
        for event in s.cfg.get('play_history', []):
            if isinstance(event, dict) and event.get('key') in updated_keys:
                track = next((s.T[i] for i in indices if key(s.T[i]) == event['key']), None)
                if track: event.update(title=track.get('title', ''), artist=track.get('artist', ''))
        save_cfg(s.cfg); s.refresh_library_list(); s.refresh_browse_pages(); s.home_refresh()
        B.status.emit(f'Updated tags on {len(indices)} track(s)' + (f'; {failed} local file(s) could not embed the changes' if failed else ''))
    def bind_shortcuts(s):
        defaults = {'toggle': 'Space', 'next': 'Ctrl+Right', 'previous': 'Ctrl+Left', 'like': 'Ctrl+L', 'queue': 'Ctrl+Q', 'search': 'Ctrl+F'}
        actions = {'toggle': s.toggle_or_activate_focused, 'next': lambda: s.step(1), 'previous': lambda: s.step(-1), 'like': lambda: s.like(s.i), 'queue': s.show_queue, 'search': lambda: (s.go(1), s.q.setFocus())}
        s.shortcuts = {}
        for name, callback in actions.items():
            shortcut = QShortcut(QKeySequence(s.cfg.get('shortcuts', {}).get(name, defaults[name])), s); shortcut.setContext(Qt.ApplicationShortcut); shortcut.activated.connect(callback); s.shortcuts[name] = shortcut
        media_keys = (('media_play', 'Key_MediaPlay', lambda: s.pl.play()), ('media_pause', 'Key_MediaPause', lambda: s.pl.pause()), ('media_toggle', 'Key_MediaTogglePlayPause', s.toggle), ('media_next', 'Key_MediaNext', lambda: s.step(1)), ('media_previous', 'Key_MediaPrevious', lambda: s.step(-1)), ('media_stop', 'Key_MediaStop', lambda: s.pl.stop()))
        for name, enum_name, callback in media_keys:
            key_value = getattr(Qt, enum_name, None)
            if key_value is None: continue
            shortcut = QShortcut(QKeySequence(key_value), s); shortcut.setContext(Qt.ApplicationShortcut); shortcut.activated.connect(callback); s.shortcuts[name] = shortcut
    def toggle_or_activate_focused(s):
        focused = s.focusWidget()
        if isinstance(focused, Springy): focused.clicked.emit(); return
        if isinstance(focused, QAbstractButton): focused.click(); return
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QKeySequenceEdit, QAbstractItemView, QSlider)): return
        s.toggle()
    def set_sleep_timer(s):
        minutes, ok = QInputDialog.getInt(s, 'Sleep timer', 'Pause playback after how many minutes? (0 cancels)', 30, 0, 720, 5)
        if not ok: return
        if minutes == 0: s.sleep_timer.stop(); s.sleep_button.setText('Sleep'); B.status.emit('Sleep timer cancelled'); return
        s.sleep_timer.start(minutes * 60 * 1000); s.sleep_button.setText(f'Sleep {minutes}m'); B.status.emit(f'Sleep timer set for {minutes} minutes')
    def sleep_now(s):
        s.pl.pause(); s.sleep_button.setText('Sleep'); B.status.emit('Sleep timer paused playback')
    def set_volume(s, value):
        s.cfg['volume'] = value; s.apply_track_volume(); save_cfg(s.cfg)
    def set_discord_presence(s, enabled):
        if s.discord: s.discord.stop(); s.discord = None
        client_id = s.discord_id.text().strip() if hasattr(s, 'discord_id') else s.cfg.get('discord_client_id', '')
        s.cfg['discord_client_id'] = client_id; s.cfg['discord_presence'] = bool(enabled); save_cfg(s.cfg)
        if enabled and client_id:
            s.discord = DiscordPresence(client_id); s.update_discord_presence()
        elif enabled:
            s.discord_chk.blockSignals(True); s.discord_chk.setChecked(False); s.discord_chk.blockSignals(False); s.cfg['discord_presence'] = False; save_cfg(s.cfg)
            QMessageBox.information(s, 'Discord Rich Presence', 'Add your Discord application ID first. Bubble connects to Discord only after you enable this option.')
    def save_discord_id(s):
        s.cfg['discord_client_id'] = s.discord_id.text().strip(); save_cfg(s.cfg)
        if s.cfg.get('discord_presence'): s.set_discord_presence(True)
    def update_discord_presence(s):
        if not s.discord or not (0 <= s.i < len(s.T)): return
        track = s.T[s.i]; playing = s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        s.discord.update(track.get('title'), track.get('artist'), playing, s.pl.position(), s.pl.duration())
    def closeEvent(s, event):
        if s.discord: s.discord.stop()
        super().closeEvent(event)
    def apply_track_volume(s):
        gain = float(s.T[s.i].get('gain_db', 0)) if 0 <= s.i < len(s.T) else 0.0
        base = max(0, min(100, int(s.cfg.get('volume', 80)))) / 100
        s.track_volume = min(1.0, base * (10 ** (gain / 20)))
        if s.fade_state is None: s.ao.setVolume(s.track_volume)
    def begin_fade(s, direction):
        duration = int(s.cfg.get('transition_fade_ms', 0))
        if duration <= 0: return
        s.fade_timer.stop(); s.fade_state = None
        current = 0.0 if direction == 'in' else s.ao.volume(); target = s.track_volume if direction == 'in' else 0.0
        if direction == 'in': s.ao.setVolume(0.0)
        if direction == 'out': s.fade_out_done = True
        s.fade_state = (time.monotonic(), duration / 1000, current, target); s.fade_timer.start()
    def fade_tick(s):
        if not s.fade_state: s.fade_timer.stop(); return
        started, duration, first, last = s.fade_state; progress = min(1.0, (time.monotonic() - started) / max(.04, duration))
        s.ao.setVolume(first + (last - first) * progress)
        if progress >= 1:
            s.fade_timer.stop(); s.fade_state = None
            if last == 0: s.ao.setVolume(s.track_volume)
    def set_audio_device(s, index):
        if index < 0: return
        device = s.audio_device_combo.itemData(index)
        if device is None:
            s.ao.setDevice(QMediaDevices.defaultAudioOutput()); s.cfg['audio_device'] = ''
        else: s.ao.setDevice(device); s.cfg['audio_device'] = bytes(device.id()).decode('utf-8', 'ignore')
        save_cfg(s.cfg)
    def set_window_opacity(s, value):
        s.setWindowOpacity(value / 100); s.cfg['window_opacity'] = value; save_cfg(s.cfg)
    def set_high_contrast(s, enabled):
        s.cfg['high_contrast'] = bool(enabled); save_cfg(s.cfg); apply_runtime_preferences(s.cfg, QApplication.instance()); s.update()
    def set_transition_fade(s, value):
        s.cfg['transition_fade_ms'] = value; save_cfg(s.cfg)
    def toggle_sidebar_section(s, page, enabled):
        s.cfg.setdefault('sidebar_sections', {})[str(page)] = bool(enabled); save_cfg(s.cfg)
        if page in s.rail: s.rail[page].setVisible(enabled)
        if not enabled and s.stack.currentIndex() == page: s.go(0)
        if page == 1 and hasattr(s, 'localchk'):
            s.localchk.blockSignals(True); s.localchk.setChecked(enabled); s.localchk.blockSignals(False)
    def visualizer_style(s, mode):
        s.visualizer.mode = mode; s.visualizer.update(); s.cfg['visualizer_style'] = mode; save_cfg(s.cfg)
    def layout_preset(s, name):
        s.cfg['layout_preset'] = name; save_cfg(s.cfg)
        if name == 'Compact': s.rpanel.hide(); s.resize(1050, 700)
        elif name == 'Wide': s.rpanel.show(); s.resize(1560, 900)
        else: s.rpanel.show(); s.resize(1340, 830)
    def open_qss_editor(s):
        dlg = QDialog(s); dlg.setWindowTitle('Bubble style editor'); dlg.resize(760, 560); layout = QVBoxLayout(dlg)
        help_text = QLabel('Custom Qt Style Sheets (QSS) extend Bubble’s built-in theme. This is Qt stylesheet syntax, not browser CSS. Keep a backup of your rules before replacing them.'); help_text.setWordWrap(True); help_text.setObjectName('dim'); layout.addWidget(help_text)
        editor = QPlainTextEdit(); editor.setPlainText(s.cfg.get('custom_qss', '')); editor.setTabStopDistance(28); layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(); apply_btn = buttons.addButton('Apply', QDialogButtonBox.AcceptRole); reset_btn = buttons.addButton('Reset to built-in', QDialogButtonBox.ResetRole); cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        def apply():
            s.cfg['custom_qss'] = editor.toPlainText()[:24000]; save_cfg(s.cfg); apply_runtime_preferences(s.cfg, QApplication.instance()); dlg.accept()
        apply_btn.clicked.connect(apply); reset_btn.clicked.connect(lambda: editor.clear()); cancel_btn.clicked.connect(dlg.reject); layout.addWidget(buttons); dlg.exec()
    def save_shortcut(s, name, sequence):
        text = sequence.toString(QKeySequence.PortableText)
        if not text: return
        s.cfg.setdefault('shortcuts', {})[name] = text; save_cfg(s.cfg)
        if name in getattr(s, 'shortcuts', {}): s.shortcuts[name].setKey(sequence)
    def find_duplicates(s):
        if getattr(s, 'duplicate_scan_active', False): return
        playable = [dict(track) for track in s.T if not track.get('rec')]
        s.duplicate_snapshot = playable; s.duplicate_scan_active = True
        B.status.emit('Scanning tags and exact file contents for duplicates...')
        def scan():
            try: B.duplicates.emit(duplicate_groups(playable))
            except Exception as exc: B.status.emit(f'Duplicate scan failed: {exc}'); B.duplicates.emit([])
        threading.Thread(target=scan, daemon=True, name='BubbleDuplicateScan').start()
    def show_duplicate_groups(s, groups):
        s.duplicate_scan_active = False; playable = getattr(s, 'duplicate_snapshot', [])
        if not groups:
            QMessageBox.information(s, 'Duplicate scan', 'No tag-matched or byte-identical audio files were found.'); B.status.emit('Duplicate scan complete: no duplicates found'); return
        dlg = QDialog(s); dlg.setWindowTitle('Possible duplicate songs'); dlg.resize(620, 520); layout = QVBoxLayout(dlg)
        note = QLabel(f'Found {len(groups)} possible duplicate group(s), using tags and exact file-content hashes. Review each group before removing entries; Bubble never deletes audio files during this scan.'); note.setWordWrap(True); note.setObjectName('dim'); layout.addWidget(note)
        view = QListWidget();
        for group in groups:
            tracks = [playable[index] for index in group]
            heading = QListWidgetItem(f"{tracks[0].get('title', 'Unknown')} — {tracks[0].get('artist', 'Unknown artist')} ({len(tracks)} copies)"); heading.setFlags(Qt.ItemIsEnabled); view.addItem(heading)
            for track in tracks:
                location = track.get('path') or track.get('url') or 'No file path'
                row = QListWidgetItem('    ' + location); row.setToolTip(location); row.setFlags(Qt.ItemIsEnabled); view.addItem(row)
        layout.addWidget(view, 1); close = QPushButton('Done'); close.clicked.connect(dlg.accept); layout.addWidget(close, 0, Qt.AlignRight); dlg.exec()
    def repair_library(s):
        folder = QFileDialog.getExistingDirectory(s, 'Choose a folder to repair and rescan')
        if not folder: return
        if getattr(s, 'repair_active', False): return
        missing = [dict(key=key(track), path=track.get('path', ''), title=track.get('title', ''), artist=track.get('artist', ''), dur=track.get('dur', 0)) for track in s.T if track.get('path') and not os.path.exists(track['path'])]
        s.repair_active = True; B.status.emit('Searching for moved songs by filename, tags, and duration...')
        def search():
            try:
                by_name = {}; by_tags = {}
                for root, _, names in os.walk(folder):
                    for name in names:
                        if not name.lower().endswith(EXT): continue
                        path = os.path.join(root, name); by_name.setdefault(name.casefold(), path)
                        meta = tag(path); title = re.sub(r'[^a-z0-9]', '', str(meta.get('title', '')).casefold()); artist = re.sub(r'[^a-z0-9]', '', str(meta.get('artist', '')).casefold())
                        if title and artist and artist not in ('unknownartist', 'unknown'): by_tags.setdefault((title, artist), []).append((path, int(meta.get('dur') or 0)))
                used = set(); repairs = []
                for track in missing:
                    path = by_name.get(os.path.basename(track['path']).casefold())
                    if not path:
                        title = re.sub(r'[^a-z0-9]', '', str(track.get('title', '')).casefold()); artist = re.sub(r'[^a-z0-9]', '', str(track.get('artist', '')).casefold())
                        candidates = [(candidate, duration) for candidate, duration in by_tags.get((title, artist), []) if candidate not in used]
                        expected = int(track.get('dur') or 0)
                        if expected: candidates = [(candidate, duration) for candidate, duration in candidates if duration and abs(duration - expected) <= 3000]
                        if candidates: path = min(candidates, key=lambda pair: abs(pair[1] - expected) if expected and pair[1] else 0)[0] if len(candidates) == 1 or expected else None
                    if path and path not in used: repairs.append((track['key'], track['path'], path)); used.add(path)
                B.repaired.emit((folder, repairs, ''))
            except Exception as exc: B.repaired.emit((folder, [], str(exc)))
        threading.Thread(target=search, daemon=True, name='BubbleLibraryRepair').start()
    def finish_repair(s, result):
        folder, repairs, error = result; s.repair_active = False
        if error: QMessageBox.warning(s, 'Folder repair failed', error); B.status.emit(f'Folder repair failed: {error}'); return
        repaired = 0
        for old_key, old_path, new_path in repairs:
            track = next((item for item in s.T if key(item) == old_key), None)
            if not track: continue
            track['path'] = new_path; s.replace_track_key(old_key, key(track)); repaired += 1
        folders = s.cfg.setdefault('folders', [])
        if folder not in folders: folders.append(folder)
        save_cfg(s.cfg); s.fl_upd(); s.scan([folder]); s.refresh_library_list(); s.refresh_browse_pages(); s.home_refresh()
        B.status.emit(f'Repaired {repaired} moved song path(s); folder scan started')
    def replace_track_key(s, old, new):
        if old == new: return
        for field in ('liked', 'recent', 'queue'):
            s.cfg[field] = [new if value == old else value for value in s.cfg.get(field, [])]
        for event in s.cfg.get('play_history', []):
            if isinstance(event, dict) and event.get('key') == old: event['key'] = new
        if old in s.history_dates: s.history_dates[new] = s.history_dates.pop(old)
        for cache in (COV, TH, GC):
            if old in cache: cache[new] = cache.pop(old)
        s.liked = set(s.cfg.get('liked', [])); s.queue_keys = list(s.cfg.get('queue', []))
        for playlist in s.cfg.get('playlists', []):
            playlist['tracks'] = [new if value == old else value for value in playlist.get('tracks', [])]
        for field in ('lyrics', 'ratings'):
            values = s.cfg.setdefault(field, {})
            if old in values: values[new] = values.pop(old)
        s.ratings = s.cfg.get('ratings', {}); s.update_queue_button()
    def restore_settings_backup(s):
        folder = os.path.join(DATA_DIR, 'backups')
        path, _ = QFileDialog.getOpenFileName(s, 'Restore settings backup', folder, 'JSON backups (*.json)')
        if not path: return
        if QMessageBox.question(s, 'Restore settings', 'Replace current settings and library metadata with this backup?') != QMessageBox.Yes: return
        if not restore_cfg_backup(path): QMessageBox.warning(s, 'Restore failed', 'That backup could not be read.'); return
        QMessageBox.information(s, 'Settings restored', 'Restart Bubble to load the restored settings and library. A fresh backup of the current settings was kept.')
    def add_genius(s, v):
        c = QLabel('Lyrics from Genius'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        d = QLabel('Want lyrics from Genius too? You need a free Genius API token: click the button, create an API client, press Generate Access Token and paste it below. Genius only gives plain lyrics (no timing), and it searches by song title only. Note: the lyricsgenius library reads lyrics from Genius web pages, which Genius does not officially allow, so use it at your own risk. The token is saved in plain text in your settings file.')
        d.setObjectName('dim'); d.setWordWrap(True); v.addWidget(d); r = QHBoxLayout(); r.setSpacing(10)
        b = QPushButton('Get a Genius API token'); b.clicked.connect(lambda: webbrowser.open('https://genius.com/api-clients')); r.addWidget(b)
        s.gt = QLineEdit(s.cfg.get('genius_token', '')); s.gt.setPlaceholderText('Paste your Genius access token'); s.gt.setEchoMode(QLineEdit.Password); s.gt.setFixedWidth(320); s.gt.editingFinished.connect(s.save_genius); r.addWidget(s.gt); r.addStretch(); v.addLayout(r)
        s.gf = QCheckBox('Try Genius before LRCLIB'); s.gf.setChecked(s.cfg.get('genius_first', False)); s.gf.toggled.connect(lambda x: s.cfg.__setitem__('genius_first', x) or save_cfg(s.cfg)); v.addWidget(s.gf)
    def save_genius(s): s.cfg['genius_token'] = s.gt.text().strip(); save_cfg(s.cfg)
    def add_bg(s, v):
        c = QLabel('Background'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c); r = QHBoxLayout(); r.setSpacing(10); s.sw = []
        for n, bg, pn in BGS: b = Swatch(n, bg, pn); b.clicked.connect(lambda n=n: s.apply_bg(n)); s.sw.append(b); r.addWidget(b)
        r.addStretch(); v.addLayout(r); r2 = QHBoxLayout(); r2.setSpacing(10); up = QPushButton('Upload animated background'); up.clicked.connect(s.pick_media)
        rm = QPushButton('Remove'); rm.setObjectName('grey'); rm.clicked.connect(lambda: s.set_media('')); r2.addWidget(up); r2.addWidget(rm); r2.addStretch(); v.addSpacing(6); v.addLayout(r2)
        h = QLabel('GIF, WebP, MP4, WebM or a still image. It plays behind everything except the lyrics panel. Big videos use more CPU.'); h.setObjectName('dim'); h.setWordWrap(True); v.addWidget(h)
        v.addWidget(QLabel('Background dimming')); ds = ClickSlider(Qt.Horizontal); s.dim_slider = ds; ds.setRange(0, 90); ds.setValue(int(s.dim * 100)); ds.setFixedWidth(260); ds.valueChanged.connect(s.set_dim); v.addWidget(ds)
    def set_dim(s, val): s.dim = val / 100; s.cfg['bg_dim'] = s.dim; save_cfg(s.cfg); s.update()
    def pick_media(s):
        f = QFileDialog.getOpenFileName(s, 'Choose a background', '', 'Backgrounds (*.gif *.webp *.mp4 *.webm *.mov *.m4v *.png *.jpg *.jpeg *.bmp)')[0]
        if not f: return
        s.clear_media(); d = os.path.join(os.path.expanduser('~'), '.bubbleplayer_bg'); dst = os.path.join(d, 'background' + os.path.splitext(f)[1].lower())
        try:
            os.makedirs(d, exist_ok=True)
            for old in os.listdir(d): os.remove(os.path.join(d, old))
            shutil.copyfile(f, dst)
        except Exception as e: B.status.emit(f'Could not copy background: {e}'); return
        s.set_media(dst)
    def clear_media(s):
        if s.mv: s.mv.stop(); s.mv.deleteLater(); s.mv = None
        if s.vp: s.vp.stop(); s.vp.setSource(QUrl()); s.vp.deleteLater(); s.vp = None
        s.bgpm = s.bgraw = None
    def set_media(s, path, save=True):
        s.clear_media(); s.bgmedia = bool(path) and os.path.exists(path)
        if s.bgmedia:
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.gif', '.webp'):
                s.mv = QMovie(path); s.mv.frameChanged.connect(lambda _: s.set_frame(s.mv.currentImage())); s.mv.start()
            elif ext in ('.mp4', '.webm', '.mov', '.m4v'):
                s.vp = QMediaPlayer(s); s.vs = QVideoSink(s); s.vp.setVideoSink(s.vs); s.vs.videoFrameChanged.connect(s.on_vframe)
                s.vp.mediaStatusChanged.connect(lambda m: (s.vp.setPosition(0), s.vp.play()) if m == QMediaPlayer.MediaStatus.EndOfMedia else None); s.vp.setSource(QUrl.fromLocalFile(path)); s.vp.play()
            else: s.set_frame(QImage(path))
        if save: s.cfg['bg_media'] = path or ''; save_cfg(s.cfg)
        s.apply_bg(s.cfg.get('bg', 'Black'), False); s.update()
    def on_vframe(s, fr):
        t = time.monotonic()
        if t - s.vt < .05: return
        s.vt = t; img = fr.toImage()
        if not img.isNull(): s.set_frame(img)
    def set_frame(s, img):
        if img.isNull(): return
        s.bgraw = img; s.bgpm = QPixmap.fromImage(img.scaled(s.size(), Qt.KeepAspectRatioByExpanding, Qt.FastTransformation)); s.update()
    def paintEvent(s, e):
        p = QPainter(s); p.fillRect(s.rect(), s.palette().window().color())
        if s.bgmedia and s.bgpm is not None:
            p.drawPixmap((s.width() - s.bgpm.width()) // 2, (s.height() - s.bgpm.height()) // 2, s.bgpm); p.fillRect(s.rect(), QColor(0, 0, 0, int(255 * s.dim)))
    def apply_bg(s, name, save=True):
        bg, pn = next((b, p) for n, b, p in BGS if n == name)
        if save: s.cfg['bg'] = name; save_cfg(s.cfg)
        apply_runtime_preferences(s.cfg, QApplication.instance())
        palette = s.palette(); palette.setColor(QPalette.Window, QColor('#faf9fc' if s.cfg.get('app_theme') == 'Light' else bg)); s.setPalette(palette)
        s.rp.base = QColor('#f5f3fa' if s.cfg.get('app_theme') == 'Light' else pn); s.rp.update()
        for b in s.sw: b.on = b.name == name; b.update()
    def set_app_theme(s, name):
        s.cfg['app_theme'] = name; save_cfg(s.cfg); apply_runtime_preferences(s.cfg, QApplication.instance())
        s.apply_bg(s.cfg.get('bg', 'Black'), False)
        for widget in s.findChildren(QWidget): widget.update()
    def card_icon(s, r, n):
        pm = spot_pm(40) if n == 'Spotify' else svc_icon('ytm', 36) if n == 'YouTube Music' else svc_icon('sc', 36) if n == 'SoundCloud' else None
        if pm: l = QLabel(); l.setPixmap(pm); r.addWidget(l)
    def close_banner(s): s.banner.hide(); s.cfg['banner_closed'] = True; save_cfg(s.cfg)
    def toggle_rp(s):
        show = not s.rp.isVisible(); s.rp_user_hidden = not show; s.rp.setVisible(show)
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
        if s.lv.synced and s.lv.lines: s.lv.tm.start()
        else: s.lv.scr = 0
        s.lv.update()
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
        if hasattr(s, 'rpanel') and not s.full and not s.yt_full:
            compact = s.width() < 1180
            s.rpanel.setVisible(not compact and not s.rp_user_hidden)
            if hasattr(s, 'q'): s.q.setFixedWidth(max(220, min(520, s.width() - (560 if compact else 850))))
            for b in getattr(s, 'service_buttons', []): b.setVisible(s.width() >= 1180)
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
        imported_playlists = {}
        for track in lst:
            names = list(track.pop('imported_playlists', []) or [])
            one = track.pop('imported_playlist', '')
            if one: names.append(one)
            for name in names:
                if name: imported_playlists.setdefault(str(name).strip(), []).append(key(track))
        for name, track_keys in imported_playlists.items():
            playlist = next((item for item in s.cfg.get('playlists', []) if item.get('name', '').casefold() == name.casefold()), None)
            if playlist is None:
                playlist = {'name': name, 'tracks': []}; s.cfg.setdefault('playlists', []).append(playlist)
            if not playlist.get('smart'):
                known = set(playlist.setdefault('tracks', []))
                for track_key in track_keys:
                    if track_key not in known: playlist['tracks'].append(track_key); known.add(track_key)
        if imported_playlists: save_cfg(s.cfg)
        new = [t for t in lst if key(t) not in s.keys]
        if not new: return
        for t in new:
            s.keys.add(key(t)); s.T.append(t); it = QListWidgetItem(); it.setData(Qt.UserRole, len(s.T) - 1); (s.lists[0].addItem(it) if not t.get('rec') else None); s.want(t, True)
        rem = [t for t in new if t['src'] != 'Local']
        if rem and save: s.cfg.setdefault('remote', []).extend(rem); save_cfg(s.cfg)
        if hasattr(s, 'library_sort'): s.refresh_library_list()
        if hasattr(s, 'playlist_tracks'): s.refresh_playlist_tracks()
        if hasattr(s, 'album_list'): s.refresh_browse_pages()
        if hasattr(s, 'soundcloud_cleanup'): s.refresh_soundcloud_streams()
        B.status.emit(f'{len(s.T)} songs in your library'); s.hdeb.start()
    def refresh_soundcloud_streams(s):
        combo = getattr(s, 'soundcloud_cleanup', None)
        if combo is None: return
        groups = {}; seen = set()
        for track in list(s.cfg.get('remote', [])) + list(s.T):
            if track.get('src') != 'SoundCloud' or track.get('rec') or track.get('path'): continue
            k = key(track)
            if k in seen: continue
            seen.add(k); label = (track.get('album') or '').strip() or f"{track.get('title') or 'SoundCloud track'} — {track.get('artist') or 'Unknown artist'}"
            groups.setdefault(label, []).append(k)
        old = combo.currentData(); combo.blockSignals(True); combo.clear()
        for label, keys in sorted(groups.items(), key=lambda item: item[0].casefold()): combo.addItem(f'{label}  ·  {len(keys)} tracks', keys)
        if old:
            for i in range(combo.count()):
                if combo.itemData(i) == old: combo.setCurrentIndex(i); break
        if combo.count() == 0: combo.addItem('No saved SoundCloud streams found', None)
        combo.blockSignals(False)
    def nuke_soundcloud_streams(s):
        removed = s.soundcloud_cleanup.currentData()
        if not removed: return
        removed = set(removed)
        label = s.soundcloud_cleanup.currentText().rsplit('  ·  ', 1)[0]
        if QMessageBox.question(s, 'Permanently remove SoundCloud playlist?', f'Remove “{label}” and its {len(removed)} saved stream link(s) from Bubble’s library, favorites, history, and saved playlists? This does not delete any audio files.', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        old_i = s.i; active_key = key(s.T[old_i]) if 0 <= old_i < len(s.T) else None
        for track in list(s.cfg.get('remote', [])) + list(s.T):
            if key(track) in removed and track.get('_source_key'): removed.add(track['_source_key'])
        current_removed = active_key in removed
        if current_removed:
            s.pl.stop(); s.pl.setSource(QUrl()); s.i = -1; s.bt.setText('No track playing'); s.ba.setText('Select a track to listen'); s.rt.setText('No track playing'); s.ra.setText('Select a track to listen'); s.mini.set(ph_pix(120)); s.rcov.set(ph_pix()); s.lv.set([], False, 'No track playing')
        s.T = [track for track in s.T if key(track) not in removed]; s.keys = {key(track) for track in s.T}
        if current_removed: s.i = -1
        elif active_key is not None: s.i = next((i for i, track in enumerate(s.T) if key(track) == active_key), -1)
        s.play_order = s.play_source_order = None; s.dg.cur = s.i
        s.cfg['remote'] = [t for t in s.cfg.get('remote', []) if key(t) not in removed]
        s.liked.difference_update(removed); s.cfg['liked'] = sorted(s.liked)
        s.cfg['recent'] = [k for k in s.cfg.get('recent', []) if k not in removed]
        s.cfg['play_history'] = [event for event in s.cfg.get('play_history', []) if not isinstance(event, dict) or event.get('key') not in removed]
        for k in removed: s.history_dates.pop(k, None)
        s.cfg['playlists'] = [{**p, 'tracks': [k for k in p.get('tracks', []) if k not in removed]} for p in s.cfg.get('playlists', [])]
        s.loading.difference_update(removed)
        for k in removed: s.cfg.get('lyrics', {}).pop(k, None); COV.pop(k, None); TH.pop(k, None); GC.pop(k, None)
        save_cfg(s.cfg)
        s.lists[0].clear()
        for i, track in enumerate(s.T):
            if not track.get('rec'): it = QListWidgetItem(); it.setData(Qt.UserRole, i); s.lists[0].addItem(it)
        by_key = {key(t): i for i, t in enumerate(s.T)}
        s.fill(s.lists[1], [i for i, t in enumerate(s.T) if key(t) in s.liked]); s.fill(s.lists[2], [by_key[k] for k in s.cfg.get('recent', []) if k in by_key])
        s.refresh_playlist_menu(); s.home_refresh(); s.refresh_heart(); s.refresh_soundcloud_streams()
        B.status.emit(f'Removed {len(removed)} SoundCloud stream link(s)')
    def on_cover(s, k, img):
        s.loading.discard(k); COV[k] = QPixmap.fromImage(img)
        TH[k] = QPixmap.fromImage(img.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        for l in s.lists: l.viewport().update()
        if k in s.homekeys:
            pm = QPixmap.fromImage(img); COV[k] = pm
            for c in s.cards:
                try:
                    if c.t and key(c.t) == k: c.pm = pm; c.update()
                except RuntimeError: pass
        if 0 <= s.i < len(s.T) and key(s.T[s.i]) == k:
            s.set_cover(s.T[s.i], COV[k])
        s.update_mini_player()

    # ---- playback
    def play(s, i, keep_order=False):
        if not keep_order: s.play_order = s.play_source_order = None
        s.fade_out_done = False
        if s.note.text().startswith('Loading'): s.note.setText('')
        s.i = i; t = s.T[i]
        if t.get('path') and 'gain_db' not in t:
            try: t['gain_db'] = tag(t['path']).get('gain_db', 0)
            except Exception: t['gain_db'] = 0
        s.apply_track_volume(); track_key = key(t); rc = s.cfg.setdefault('recent', []); rc[:] = [track_key] + [x for x in rc if x != track_key]; del rc[30:]
        now = datetime.datetime.now().astimezone(); played_at = now.isoformat(timespec='minutes')
        history = s.cfg.setdefault('play_history', []); history[:] = [event for event in history if not isinstance(event, dict) or event.get('key') != track_key]
        history.insert(0, {'key': track_key, 'title': t.get('title', ''), 'artist': t.get('artist', ''), 'played_at': played_at}); del history[500:]
        s.history_dates[track_key] = now.strftime('%b ') + str(now.day) + now.strftime(', %Y  %I:%M %p')
        save_cfg(s.cfg); s.dg.cur = i
        if len(s.lists) > 2 and s.stack.currentIndex() == 3: s.fill_play_history()
        s.pl.stop(); s.bt.setText(t['title']); s.ba.setText(t['artist']); s.rt.setText(t['title']); s.ra.setText(t['artist']); s.refresh_heart()
        pm = COV.get(key(t)); lyr = None
        if t['path'] and not (t.get('_temporary') and s.cfg.get('download_songs')):
            s.pl.setSource(QUrl.fromLocalFile(t['path'])); s.pl.play(); s.begin_fade('in'); cov, lyr = extras(t['path']) if mutagen else (None, None)
            if cov: q = QPixmap(); q.loadFromData(cov); pm = q if not q.isNull() else pm
        else: B.status.emit('Downloading song...' if s.cfg.get('download_songs') else 'Loading stream...'); threading.Thread(target=s.res, args=(i, t), daemon=True).start()
        s.set_cover(t, pm or gen_cover(t['title'] + t['artist'])); s.set_lyrics(i, t, s.cfg.get('lyrics', {}).get(t.get('_source_key') or key(t)) or lyr)
        s.update_discord_presence(); s.update_mini_player()
        for l in s.lists: l.viewport().update()
    def set_cover(s, t, pm):
        COV[key(t)] = sq(pm, 360); s.mini.set(pm); s.rcov.set(pm); s.rp.set_cover(pm)
        s.setWindowTitle(f"{t.get('title', 'Bubble')} — {t.get('artist', 'Bubble Player')} · Bubble")
        s.setWindowIcon(QIcon(COV[key(t)]))
        if s.cfg.get('artwork_accent', False) and getattr(s, 'last_dynamic_key', None) != key(t):
            sample = artwork_accent(pm)
            s.cfg['accent_color'] = sample.name(); s.last_dynamic_key = key(t); save_cfg(s.cfg)
            apply_runtime_preferences(s.cfg, QApplication.instance())

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
            except ImportError as e:
                detail = f'This needs yt-dlp or spotDL. Install dependencies with: pip install -r requirements.txt ({e})'
                B.task_error.emit(ok, detail); B.status.emit(detail)
            except Exception as e: B.task_error.emit(ok, str(e)); B.status.emit(f'{ok} failed: {e}')
            finally: B.task_done.emit(ok)
        threading.Thread(target=job, daemon=True).start()
    def on_task_done(s, name):
        if name == 'Spotify spotDL':
            s.spotify_download_btn.setEnabled(True); s.spotify_cancel_btn.setEnabled(False); s.spotify_pause_btn.setEnabled(False); s.spotify_pause_btn.setText('Pause'); s.download_paused = False; s.download_suspended = []; s.spotify_retry_btn.setEnabled(bool(getattr(s, 'spotify_failed', False))); s.download_proc = None
    def on_download_started(s):
        s.download_paused = False; s.download_suspended = []; s.spotify_pause_btn.setEnabled(True); s.spotify_pause_btn.setText('Pause')
    def on_task_error(s, name, detail):
        if name == 'Spotify spotDL':
            s.spotify_failed = True; s.spotify_error = detail; s.spotify_retry_btn.setEnabled(True); s.spotify_retry_btn.setToolTip(detail)
    def cancel_spotify_download(s):
        if getattr(s, 'download_paused', False): s.resume_download_processes()
        s.download_cancel.set(); proc = s.download_proc
        if proc and proc.poll() is None:
            try: proc.terminate()
            except OSError: pass
        B.status.emit('Cancelling Spotify download...')
    def resume_download_processes(s):
        for process in reversed(getattr(s, 'download_suspended', [])):
            try: process.resume()
            except Exception: pass
        s.download_suspended = []; s.download_paused = False
        if hasattr(s, 'spotify_pause_btn'): s.spotify_pause_btn.setText('Pause')
    def toggle_download_pause(s):
        proc = s.download_proc
        if not proc or proc.poll() is not None: return
        if getattr(s, 'download_paused', False):
            s.resume_download_processes(); B.status.emit('Spotify download resumed'); return
        suspended = []
        try:
            import psutil
            root = psutil.Process(proc.pid); children = root.children(recursive=True)
            for process in children: process.suspend(); suspended.append(process)
            root.suspend(); suspended.insert(0, root); s.download_suspended = suspended; s.download_paused = True
            s.spotify_pause_btn.setText('Resume'); B.status.emit('Spotify download paused')
        except Exception as exc:
            s.download_suspended = suspended; s.resume_download_processes(); B.status.emit(f'Could not pause download: {exc}')
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
    def import_playlist(s):
        services = ['Spotify (downloads with spotDL)', 'YouTube', 'YouTube Music', 'SoundCloud', 'Deezer', 'Apple Music library export']
        service, ok = QInputDialog.getItem(s, 'Import a playlist', 'Choose a music service:', services, 0, False)
        if not ok: return
        if service == 'Apple Music library export':
            s.apple(); return
        url, ok = QInputDialog.getText(s, 'Import a playlist', f'Paste a public {service.split(" (")[0]} playlist URL:')
        if not ok or not url.strip(): return
        url = url.strip()
        host = (urllib.parse.urlparse(url).hostname or '').lower()
        if not host or not url.lower().startswith(('https://', 'http://')):
            QMessageBox.warning(s, 'Playlist URL', 'Enter a complete public playlist URL.'); return
        if service.startswith('Spotify'):
            if 'spotify.com' not in host:
                QMessageBox.warning(s, 'Playlist URL', 'That does not look like a Spotify URL.'); return
            s.spotify_url.setText(url); s.download_spotify_link(); return
        if service == 'Deezer':
            if 'deezer.com' not in host:
                QMessageBox.warning(s, 'Playlist URL', 'That does not look like a Deezer URL.'); return
            B.status.emit('Importing public Deezer playlist...'); s.run(lambda: deezer_import(url), 'Deezer'); return
        allowed = ('youtube.com', 'youtu.be', 'music.youtube.com') if service in ('YouTube', 'YouTube Music') else ('soundcloud.com', 'on.soundcloud.com')
        if not any(host == domain or host.endswith('.' + domain) for domain in allowed):
            QMessageBox.warning(s, 'Playlist URL', f'That does not look like a {service} URL.'); return
        B.status.emit(f'Importing {service} playlist...'); s.run(lambda: yt_import(url, service), service)
    def link(s, src):
        u, ok = QInputDialog.getText(s, src, f'Paste a {src} song, album or playlist link:')
        if ok and u.strip(): B.status.emit('Importing...'); s.run(lambda: yt_import(u.strip(), src), src)
    def deezer(s):
        url, ok = QInputDialog.getText(s, 'Deezer', 'Paste a public Deezer playlist URL:')
        if ok and url.strip(): B.status.emit('Importing public Deezer playlist...'); s.run(lambda: deezer_import(url.strip()), 'Deezer')
    def apple(s):
        f = QFileDialog.getOpenFileName(s, 'Apple Music library file', '', 'Library (*.xml *.plist)')[0]
        if f: s.run(lambda: apple_import(f), 'Apple Music')
    def bounce(s, v): PH['C'] = .5 - v / 100 * .30; s.cfg['damp'] = PH['C']; save_cfg(s.cfg)
    def reset_library(s):
        if QMessageBox.question(s, 'Reset library', 'Remove all songs and saved library entries? Downloaded audio in Bubble\\songs will stay on disk.') != QMessageBox.Yes: return
        s.T.clear(); s.keys.clear(); s.liked.clear(); s.queue_keys.clear(); s.ratings.clear(); s.history_dates.clear(); s.cfg['queue'] = []; s.cfg['ratings'] = {}; s.cfg['remote'] = []; s.cfg['recent'] = []; s.cfg['play_history'] = []; s.cfg['liked'] = []; s.cfg['folders'] = [SONGS_DIR]; save_cfg(s.cfg); s.fl_upd(); s.update_queue_button()
        for lw in s.lists: lw.clear()
        COV.clear(); TH.clear(); s.i = -1; s.pl.stop(); s.bt.setText('No track playing'); s.ba.setText('Select a track to listen'); s.rt.setText('No track playing'); s.ra.setText('Select a track to listen'); s.home_refresh(); B.status.emit('Library reset')
    def download_mode(s, on): s.cfg['download_songs'] = on; save_cfg(s.cfg)
    def local_library_mode(s, on):
        s.cfg['show_local_files'] = on; save_cfg(s.cfg); s.rail[1].setVisible(on)
        if hasattr(s, 'sidebar_checks') and 1 in s.sidebar_checks:
            s.sidebar_checks[1].blockSignals(True); s.sidebar_checks[1].setChecked(on); s.sidebar_checks[1].blockSignals(False)
            s.cfg.setdefault('sidebar_sections', {})['1'] = bool(on); save_cfg(s.cfg)
        if not on and s.stack.currentIndex() == 1: s.go(0)
    def cursor_mode(s, on):
        global HAND_CURSOR
        HAND_CURSOR = not on; s.cfg['no_hand_cursor'] = on; save_cfg(s.cfg)
        cursor = Qt.ArrowCursor if on else Qt.PointingHandCursor
        for cls in (Springy, Pill, SeekBar, ClickSlider):
            for widget in s.findChildren(cls): widget.setCursor(cursor)
    def performance_mode(s, on):
        global PERFORMANCE_MODE
        PERFORMANCE_MODE = on; s.cfg['performance_mode'] = on; save_cfg(s.cfg)
    def update_accent_setting(s, *_):
        color = QColor.fromHsv(s.accent_hue.value(), int(s.accent_intensity.value() * 2.55), 230).name()
        s.cfg['accent_color'] = color; s.cfg['accent_intensity'] = s.accent_intensity.value(); save_cfg(s.cfg)
        apply_runtime_preferences(s.cfg, QApplication.instance())
        s.apply_bg(s.cfg.get('bg', 'Black'), False)
        for widget in s.findChildren(QWidget): widget.update()
    def playback_speed(s, v): s.pl.setPlaybackRate(v / 100); s.cfg['playback_speed'] = v; save_cfg(s.cfg)
    def reset_settings(s):
        if QMessageBox.question(s, 'Reset settings', 'Restore default preferences? Your library, downloaded songs, folders, and saved lyrics will be kept.') != QMessageBox.Yes: return
        keep = {k: s.cfg[k] for k in ('remote', 'recent', 'play_history', 'liked', 'lyrics', 'ratings', 'queue', 'folders', 'playlists', 'spotify_id', 'welcome_complete', 'desktop_shortcut', 'start_menu_shortcut') if k in s.cfg}
        s.cfg = {**keep, 'bg': 'Black', 'bg_media': '', 'bg_dim': .55, 'damp': .30, 'download_songs': False,
                 'playback_speed': 100, 'lyrics_online': True, 'genius_first': False, 'genius_token': '', 'visualizer': True, 'banner_closed': False,
                 'show_local_files': True, 'sidebar_sections': {str(page): True for page in (1, 2, 3, 5, 6, 7, 8)},
                 'no_hand_cursor': False, 'performance_mode': False, 'accent_color': '#33d6e8', 'accent_intensity': 90,
                 'volume': 80, 'transition_fade_ms': 0, 'visualizer_style': 'Bars', 'window_opacity': 100,
                 'layout_preset': 'Standard', 'app_theme': 'Dark', 'artwork_accent': False, 'custom_qss': '', 'audio_device': '', 'high_contrast': False}
        PH['C'] = .30; s.pl.setPlaybackRate(1.0); save_cfg(s.cfg)
        s.localchk.setChecked(True); s.cursorchk.setChecked(False); s.performancechk.setChecked(False)
        s.dlchk.setChecked(False); s.speed_slider.setValue(100); s.chk.setChecked(True); s.gf.setChecked(False); s.gt.clear()
        for check in s.sidebar_checks.values(): check.setChecked(True)
        s.visualizer_chk.setChecked(True); s.visualizer_combo.setCurrentText('Bars'); s.visualizer.mode = 'Bars'
        s.fade_slider.setValue(0); s.vol.setValue(80); s.opacity_slider.setValue(100); s.layout_combo.setCurrentText('Standard'); s.app_theme_combo.setCurrentText('Dark')
        s.artwork_accent.setChecked(False); s.audio_device_combo.setCurrentIndex(0)
        s.high_contrast_chk.setChecked(False)
        s.accent_hue.setValue(QColor('#33d6e8').hue()); s.accent_intensity.setValue(90); apply_runtime_preferences(s.cfg, QApplication.instance())
        s.bounce_slider.setValue(67); s.dim_slider.setValue(55); s.set_media('', False); s.apply_bg('Black', False)
        s.banner.setVisible(True)
        B.status.emit('Preferences restored to defaults')
    def open_data_folder(s):
        os.makedirs(DATA_DIR, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR))
    def open_songs_folder(s):
        os.makedirs(SONGS_DIR, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(SONGS_DIR))
    def spotdl_track(s, t):
        query = t.get('url') or f"{t.get('artist', '')} - {t.get('title', '')}"
        persistent = bool(s.cfg.get('download_songs'))
        base = SONGS_DIR if persistent else os.path.join(tempfile.gettempdir(), 'Bubble', 'spotdl')
        digest = hashlib.sha1(key(t).encode('utf-8', errors='ignore')).hexdigest()[:12]
        folder = os.path.join(base, digest); os.makedirs(folder, exist_ok=True)
        cached = next((os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(EXT)), None)
        if cached: return cached
        output = os.path.join(folder, '{artists} - {title}.{output-ext}')
        args = ['download', query, '--output', output, '--format', 'mp3', '--lyrics', 'synced', '--generate-lrc', '--threads', '1', '--cache-path', os.path.join(DATA_DIR, 'spotdl-cache'), '--print-errors']
        result = subprocess.run(spotdl_command(args), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900, cwd=DATA_DIR)
        found = next((os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(EXT)), None)
        if result.returncode or not found:
            detail = (result.stderr or result.stdout or 'spotDL did not create an audio file').strip()
            raise RuntimeError(detail[-1200:])
        return found
    def spotdl_import(s, url):
        s.download_count = 0
        playlist_name = ''
        if '/playlist/' in url:
            try:
                metadata = fetch('https://open.spotify.com/oembed?' + urllib.parse.urlencode({'url': url}))
                playlist_name = metadata.get('title', '')
            except Exception: pass
        digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]
        folder = os.path.join(SONGS_DIR, 'spotify_' + digest); os.makedirs(folder, exist_ok=True)
        output = os.path.join(folder, '{artists} - {title}.{output-ext}')
        args = ['download', url, '--output', output, '--format', 'mp3', '--lyrics', 'synced', '--generate-lrc', '--threads', '2', '--cache-path', os.path.join(DATA_DIR, 'spotdl-cache'), '--print-errors']
        log_path = os.path.join(folder, 'spotdl.log'); emitted = set(); sizes = {}; tracks_found = 0
        def audio_files():
            return [os.path.join(root, name) for root, _, names in os.walk(folder) for name in names if name.lower().endswith(EXT)]
        def emit_ready(paths):
            nonlocal tracks_found
            fresh = [path for path in paths if path not in emitted]
            if not fresh: return
            batch = []
            for path in fresh:
                if not os.path.isfile(path) or os.path.getsize(path) == 0: continue
                track = tag(path); track['src'] = 'Spotify'
                stem = os.path.splitext(os.path.basename(path))[0]
                if ' - ' in stem:
                    file_artist, file_title = (part.strip() for part in stem.split(' - ', 1))
                    if file_artist and (not track.get('artist') or track.get('artist') == 'Unknown artist'): track['artist'] = file_artist
                    if file_title and (not track.get('title') or track.get('title') == stem): track['title'] = file_title
                if playlist_name: track['imported_playlist'] = playlist_name
                batch.append(track); emitted.add(path)
            if batch:
                B.imported.emit(batch); tracks_found += len(batch)
                B.status.emit(f'Spotify download: {tracks_found} song(s) added to your library')
        started = time.monotonic(); next_status_at = started
        with open(log_path, 'w', encoding='utf-8', errors='replace') as log:
            proc = subprocess.Popen(spotdl_command(args), stdout=log, stderr=subprocess.STDOUT, cwd=DATA_DIR)
            s.download_proc = proc
            B.download_started.emit()
            while proc.poll() is None:
                paths = audio_files(); stable = []
                for path in paths:
                    try: size = os.path.getsize(path)
                    except OSError: continue
                    prev_size, stable_polls = sizes.get(path, (None, 0))
                    stable_polls = stable_polls + 1 if size == prev_size else 0
                    sizes[path] = (size, stable_polls)
                    if size > 0 and stable_polls >= 2: stable.append(path)
                emit_ready(stable)
                if s.download_cancel.is_set():
                    try: proc.terminate()
                    except OSError: pass
                    try: proc.wait(timeout=8)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                    break
                if getattr(s, 'download_paused', False):
                    time.sleep(1); continue
                if time.monotonic() - started > 3600:
                    proc.kill(); proc.wait(); raise TimeoutError('spotDL timed out after one hour')
                now = time.monotonic()
                if now >= next_status_at:
                    elapsed = fmt(int((now - started) * 1000))
                    B.status.emit(f'SpotDL is still working · {tracks_found} song(s) added · {elapsed} elapsed')
                    next_status_at = now + 4
                time.sleep(1)
        s.download_proc = None
        if s.download_cancel.is_set():
            B.status.emit(f'Spotify download cancelled; {tracks_found} completed song(s) are in your library')
            return []
        paths = audio_files(); emit_ready(paths)
        if proc.returncode and not tracks_found:
            try: detail = open(log_path, encoding='utf-8', errors='replace').read()[-1200:]
            except Exception: detail = ''
            raise RuntimeError(detail.strip() or 'spotDL could not download this Spotify link')
        if not tracks_found:
            raise RuntimeError('spotDL finished but did not create any audio files')
        if proc.returncode: raise RuntimeError(f'spotDL reported some errors after adding {tracks_found} song(s). Check {log_path} and use Retry to try the playlist again.')
        else: B.status.emit(f'Spotify download complete: {tracks_found} song(s) added to your library')
        return []
    def download_spotify_link(s):
        url = s.spotify_url.text().strip()
        if not url:
            B.status.emit('Paste a Spotify track, album, or playlist link first'); return
        if not re.match(r'^https?://(open\.spotify\.com/|spotify\.link/)', url, re.I):
            B.status.emit('Enter a Spotify track, album, or playlist URL'); return
        s.last_spotify_url = url; s.download_cancel.clear(); s.spotify_failed = False; s.spotify_error = ''; s.spotify_retry_btn.setEnabled(False); s.spotify_pause_btn.setEnabled(False); s.spotify_download_btn.setEnabled(False); s.spotify_cancel_btn.setEnabled(True); B.status.emit('Starting Spotify download with spotDL...')
        s.run(lambda: s.spotdl_import(url), 'Spotify spotDL')
    def retry_spotify_download(s):
        if not getattr(s, 'spotify_failed', False): return
        if s.last_spotify_url: s.spotify_url.setText(s.last_spotify_url)
        s.download_spotify_link()

    # ---- playback
    def res(s, i, t):
        try:
            if t.get('src') == 'Spotify':
                B.status.emit('SpotDL is matching and preparing the song...')
                path = s.spotdl_track(t); B.resolved.emit(i, 'local:' + path, None)
            elif s.cfg.get('download_songs'):
                import yt_dlp
                safe = re.sub(r'[<>:"/\\|?*]+', '', f"{t['artist']} - {t['title']}").strip()[:150] or 'Bubble song'
                opts = {'quiet': True, 'noplaylist': True, 'format': 'bestaudio/best', 'outtmpl': os.path.join(SONGS_DIR, safe + '.%(ext)s'), 'postprocessors': [{'key': 'FFmpegMetadata'}]}
                with yt_dlp.YoutubeDL(opts) as y: info = y.extract_info(t['url'] or f"ytsearch1:{t['artist']} - {t['title']}", download=True)
                if info.get('entries'): info = next(x for x in info['entries'] if x)
                path = y.prepare_filename(info)
                if not os.path.exists(path):
                    stem = os.path.splitext(path)[0]; path = next((stem + x for x in EXT if os.path.exists(stem + x)), path)
                if mutagen and os.path.exists(path):
                    try:
                        f = mutagen.File(path, easy=True)
                        if f is not None:
                            f['title'] = t['title']; f['artist'] = t['artist']
                            if t.get('album'): f['album'] = t['album']
                            f.save()
                    except Exception: pass
                B.resolved.emit(i, 'local:' + path, None)
            else:
                u, d = resolve(t); B.resolved.emit(i, u, d)
        except ImportError: B.status.emit('Spotify playback needs spotDL. Install it with: pip install spotdl' if t.get('src') == 'Spotify' else 'Streaming needs yt-dlp. Run: pip install yt-dlp')
        except Exception as e: B.status.emit(f'Could not load stream: {e}')
    def on_resolved(s, i, url, data):
        if i != s.i: return
        if url.startswith('local:'):
            path = url[6:]; track = s.T[i]
            track['_source_key'] = track.get('_source_key') or key(track)
            temporary = track.get('src') == 'Spotify' and not s.cfg.get('download_songs')
            if temporary:
                track = dict(track); s.T[i] = track; track['_temporary'] = True
            track['path'] = path
            track['gain_db'] = tag(path).get('gain_db', track.get('gain_db', 0)); s.apply_track_volume()
            if not temporary:
                for saved in s.cfg.get('remote', []):
                    same = (saved.get('url') == track.get('url')) if track.get('url') else (saved.get('title') == track.get('title') and saved.get('artist') == track.get('artist'))
                    if same: saved['path'] = path
                save_cfg(s.cfg)
            s.pl.setSource(QUrl.fromLocalFile(path))
        else: s.pl.setSource(QUrl(url))
        s.pl.play(); s.begin_fade('in'); s.note.setText('')
        if url.startswith('local:'):
            cover, lyric_text = extras(url[6:])
            if cover:
                q = QPixmap(); q.loadFromData(cover)
                if not q.isNull(): s.set_cover(s.T[i], q)
            lyric_text = lyric_text or s.cfg.get('lyrics', {}).get(s.T[i].get('_source_key') or key(s.T[i]))
            if lyric_text:
                s.cfg.setdefault('lyrics', {})[s.T[i].get('_source_key') or key(s.T[i])] = lyric_text; save_cfg(s.cfg)
                write_lrc(url[6:], lyric_text); s.set_lyrics(i, s.T[i], lyric_text)
        if data:
            q = QPixmap(); q.loadFromData(data)
            if not q.isNull(): s.set_cover(s.T[i], q)
    def set_lyrics(s, i, t, txt):
        if txt: s.lv.set(*parse_lrc(txt))
        else:
            s.lv.set([], False, 'Searching for lyrics...' if s.cfg.get('lyrics_online', True) else 'No lyrics found')
            if s.cfg.get('lyrics_online', True): threading.Thread(target=s.web_lyrics, args=(i, t), daemon=True).start()
    def lrclib_text(s, t):
        pick = lambda j: (j.get('syncedLyrics') or j.get('plainLyrics') or '') if isinstance(j, dict) else ''; txt = ''; a = '' if t['artist'].startswith('Unknown') else t['artist']
        try: txt = pick(fetch('https://lrclib.net/api/get?' + urllib.parse.urlencode(dict(artist_name=a, track_name=t['title'], album_name=t['album'], duration=t['dur'] // 1000))))
        except Exception: pass
        for q in (dict(track_name=t['title'], artist_name=a), dict(q=(a + ' ' + t['title']).strip())):
            if txt: break
            try:
                res = fetch('https://lrclib.net/api/search?' + urllib.parse.urlencode({k: v for k, v in q.items() if v}))
                txt = next((pick(r) for r in res if r.get('syncedLyrics')), '') or next((pick(r) for r in res if r.get('plainLyrics')), '')
            except Exception: pass
        return txt
    def genius_text(s, t):
        tok = s.cfg.get('genius_token', '').strip()
        if not tok: return ''
        try: from lyricsgenius import Genius
        except ImportError: B.status.emit('Genius lyrics need the lyricsgenius package: pip install lyricsgenius'); return ''
        g = Genius(tok, verbose=False, remove_section_headers=True, skip_non_songs=True, timeout=15, retries=1)
        song = g.search_song(t['title'], t.get('artist') or None)
        txt = song.lyrics if song else ''
        return re.sub(r'\d*Embed$', '', re.sub(r'^[^\n]*Lyrics\n', '', txt, count=1)).strip()
    def web_lyrics(s, i, t):
        fns = [s.genius_text, s.lrclib_text] if s.cfg.get('genius_first') else [s.lrclib_text, s.genius_text]; txt = ''
        for fn in fns:
            if not txt:
                try: txt = fn(t) or ''
                except Exception as e: B.status.emit(f'Lyrics lookup problem: {e}')
        B.lyrics.emit(i, txt)
    def on_audio_buffer(s, buffer):
        try:
            if not buffer.isValid(): return
            fmt = buffer.format(); kind = fmt.sampleFormat(); raw = bytes(buffer.constData())
            if kind == QAudioFormat.SampleFormat.Float: code, scale = '<f', 1.0
            elif kind == QAudioFormat.SampleFormat.Int16: code, scale = '<h', 32768.0
            elif kind == QAudioFormat.SampleFormat.Int32: code, scale = '<i', 2147483648.0
            elif kind == QAudioFormat.SampleFormat.UInt8: code, scale = '<B', 128.0
            else: return
            size = struct.calcsize(code); channels = max(1, fmt.channelCount()); count = len(raw) // size
            unpacked = [x[0] for x in struct.iter_unpack(code, raw[:count * size])]
            mono = []
            for j in range(0, len(unpacked) - channels + 1, channels):
                value = sum(unpacked[j:j + channels]) / channels
                if kind == QAudioFormat.SampleFormat.UInt8: value -= 128
                mono.append(max(-1.0, min(1.0, value / scale)))
            s.visualizer.feed(mono, fmt.sampleRate()); s.seek.setSpectrum(s.visualizer.levels)
        except Exception: pass
    def on_lyrics(s, i, txt):
        if i != s.i: return
        if not txt:
            s.lv.set([], False, 'No lyrics found for this song'); return
        track = s.T[i]; lyric_key = track.get('_source_key') or key(track)
        s.cfg.setdefault('lyrics', {})[lyric_key] = txt; save_cfg(s.cfg)
        if track.get('path'): write_lrc(track['path'], txt)
        s.lv.set(*parse_lrc(txt))
    def on_pos(s, ms):
        if not s.seek.isSliderDown(): s.seek.setValue(ms)
        s.lv.pos(ms)
        fade = int(s.cfg.get('transition_fade_ms', 0)); duration = s.pl.duration()
        if fade > 0 and duration > 0 and duration - ms <= fade and s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState and not getattr(s, 'fade_out_done', False): s.begin_fade('out')
    def toggle(s):
        if s.i < 0 and s.T: s.play(0)
        elif s.pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState: s.pl.pause()
        else: s.pl.play()
    def step(s, d, auto=False):
        if not s.T: return
        if d > 0 and s.queue_keys:
            by_key = {key(track): i for i, track in enumerate(s.T)}
            while s.queue_keys:
                queued = s.queue_keys.pop(0)
                if queued in by_key:
                    s.cfg['queue'] = s.queue_keys; save_cfg(s.cfg); s.update_queue_button(); s.play(by_key[queued]); return
            s.cfg['queue'] = []; save_cfg(s.cfg); s.update_queue_button()
        if s.play_order:
            if auto and s.rep == 2: s.pl.setPosition(0); s.pl.play(); return
            if not auto and d < 0 and s.pl.position() > 3000: s.pl.setPosition(0); return
            try: pos = s.play_order.index(s.i)
            except ValueError: pos = 0
            nxt = pos + d
            if auto and nxt >= len(s.play_order) and s.rep == 0: return
            if auto and s.rep == 1: nxt %= len(s.play_order)
            elif not auto: nxt %= len(s.play_order)
            if 0 <= nxt < len(s.play_order): s.play(s.play_order[nxt], keep_order=True)
            return
        if auto and s.rep == 2: s.pl.setPosition(0); s.pl.play(); return
        if auto and s.rep == 0 and not s.shuf and s.i >= len(s.T) - 1: return
        if not auto and d < 0 and s.pl.position() > 3000: s.pl.setPosition(0); return
        s.play(random.randrange(len(s.T)) if s.shuf else (s.i + d) % len(s.T))
    def flag(s, k):
        if k == 'shuf':
            s.shuf = not s.shuf; s.bsh.on = s.shuf; s.bsh.update()
            if s.play_order and s.play_source_order:
                try: pos = s.play_order.index(s.i)
                except ValueError: pos = 0
                if s.shuf:
                    tail = s.play_order[pos + 1:]; random.shuffle(tail); s.play_order = s.play_order[:pos + 1] + tail
                else: s.play_order = list(s.play_source_order)
        else: s.rep = (s.rep + 1) % 3; s.brp.on = s.rep > 0; s.brp.update()
    def keyPressEvent(s, e):
        if e.key() == Qt.Key_Space and not isinstance(s.focusWidget(), QLineEdit): s.toggle()
        elif e.key() == Qt.Key_Escape and s.yt_full: s.exit_youtube_fullscreen()
        elif e.key() == Qt.Key_Escape and s.full: s.toggle_full()
        else: super().keyPressEvent(e)
    def want(s, t, remote=True, force=False):
        k = key(t)
        if k in COV or (not force and (k in TH or k in s.loading)): return
        if t['path'] or (remote and t['cover_url']): s.loading.add(k); s.cq.put((k, t['path'], t['cover_url']))
    def mk_settings(s):
        sc = QScrollArea(); sc.setWidgetResizable(True); w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(28, 24, 28, 24); v.setSpacing(10); sc.viewport().setAutoFillBackground(False)
        t = QLabel('Settings'); t.setObjectName('h1'); v.addWidget(t); s.note = QLabel(''); s.note.setStyleSheet('color:#9a9a9a'); v.addWidget(s.note)
        c = QLabel('Music downloads and imports'); c.setObjectName('h2'); v.addSpacing(8); v.addWidget(c)
        d = QLabel('Download Spotify tracks, albums, and playlists with spotDL, or import songs from other services.'); d.setObjectName('dim'); d.setWordWrap(True); v.addWidget(d)
        migrate = QPushButton('Import a playlist from a service'); migrate.clicked.connect(s.import_playlist); v.addWidget(migrate, 0, Qt.AlignLeft)
        f = QFrame(); f.setObjectName('svc'); r = QHBoxLayout(f); r.setContentsMargins(18, 14, 18, 14); s.card_icon(r, 'Spotify')
        col = QVBoxLayout(); a = QLabel('Spotify'); a.setStyleSheet('font-size:16px;font-weight:700'); b = QLabel('Paste a Spotify track, album, or playlist URL. spotDL downloads audio with song tags and cover art into Bubble\\songs.'); b.setObjectName('dim'); b.setWordWrap(True); col.addWidget(a); col.addWidget(b); r.addLayout(col, 1)
        s.spotify_url = QLineEdit(); s.spotify_url.setPlaceholderText('https://open.spotify.com/track/... or playlist/...'); s.spotify_url.setMinimumWidth(260); s.spotify_url.returnPressed.connect(s.download_spotify_link); r.addWidget(s.spotify_url, 1)
        k = QPushButton('Download with spotDL'); s.spotify_download_btn = k; k.clicked.connect(s.download_spotify_link); r.addWidget(k)
        s.spotify_retry_btn = QPushButton('Retry'); s.spotify_retry_btn.setObjectName('grey'); s.spotify_retry_btn.setEnabled(False); s.spotify_retry_btn.clicked.connect(s.retry_spotify_download); r.addWidget(s.spotify_retry_btn)
        s.spotify_pause_btn = QPushButton('Pause'); s.spotify_pause_btn.setObjectName('grey'); s.spotify_pause_btn.setEnabled(False); s.spotify_pause_btn.clicked.connect(s.toggle_download_pause); r.addWidget(s.spotify_pause_btn)
        s.spotify_cancel_btn = QPushButton('Cancel'); s.spotify_cancel_btn.setObjectName('grey'); s.spotify_cancel_btn.setEnabled(False); s.spotify_cancel_btn.clicked.connect(s.cancel_spotify_download); r.addWidget(s.spotify_cancel_btn); v.addWidget(f)
        for n, ds, bt, fn in [('YouTube Music', 'Paste a song, album or playlist link. Streams audio directly. Needs yt-dlp.', 'Import link', lambda: s.link('YouTube Music')),
                              ('SoundCloud', 'Paste a track or playlist link. Streams audio directly. Needs yt-dlp.', 'Import link', lambda: s.link('SoundCloud')),
                              ('Deezer', 'Import a public playlist from Deezer. Track audio is resolved by title and artist.', 'Import public playlist', s.deezer),
                              ('Apple Music', 'Import a library exported from the Music app (File > Library > Export Library). Only songs saved as files can play; Apple blocks streaming.', 'Import library file', s.apple)]:
            f = QFrame(); f.setObjectName('svc'); r = QHBoxLayout(f); r.setContentsMargins(18, 14, 18, 14); s.card_icon(r, n); col = QVBoxLayout(); a = QLabel(n); a.setStyleSheet('font-size:16px;font-weight:700')
            b = QLabel(ds); b.setObjectName('dim'); b.setWordWrap(True); col.addWidget(a); col.addWidget(b); r.addLayout(col, 1); k = QPushButton(bt); k.clicked.connect(fn); r.addWidget(k)
            v.addWidget(f)
        c = QLabel('SoundCloud stream cleanup'); c.setObjectName('h2'); v.addSpacing(8); v.addWidget(c)
        cleanup_note = QLabel('Remove a saved SoundCloud playlist from Bubble. This clears stream links and library entries; it does not delete downloaded audio files.'); cleanup_note.setObjectName('dim'); cleanup_note.setWordWrap(True); v.addWidget(cleanup_note)
        cleanup_row = QHBoxLayout(); s.soundcloud_cleanup = QComboBox(); s.soundcloud_cleanup.setMinimumWidth(280); cleanup_row.addWidget(s.soundcloud_cleanup, 1)
        refresh_sc = QPushButton('Refresh'); refresh_sc.setObjectName('grey'); refresh_sc.clicked.connect(s.refresh_soundcloud_streams); cleanup_row.addWidget(refresh_sc)
        nuke_sc = QPushButton('Permanently remove'); nuke_sc.setObjectName('grey'); nuke_sc.clicked.connect(s.nuke_soundcloud_streams); cleanup_row.addWidget(nuke_sc); v.addLayout(cleanup_row)
        s.refresh_soundcloud_streams()
        c = QLabel('Playback'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        s.localchk = QCheckBox('Show local files in the My Files tab'); s.localchk.setChecked(s.cfg.get('show_local_files', True)); s.localchk.toggled.connect(s.local_library_mode); v.addWidget(s.localchk)
        s.cursorchk = QCheckBox('Use a normal arrow cursor'); s.cursorchk.setChecked(s.cfg.get('no_hand_cursor', False)); s.cursorchk.toggled.connect(s.cursor_mode); v.addWidget(s.cursorchk)
        s.performancechk = QCheckBox('Reduce decorative hover animations'); s.performancechk.setChecked(s.cfg.get('performance_mode', False)); s.performancechk.toggled.connect(s.performance_mode); v.addWidget(s.performancechk)
        s.dlchk = QCheckBox('Download songs to %AppData%\\Bubble\\songs (instead of temporary stream links)'); s.dlchk.setChecked(s.cfg.get('download_songs', False)); s.dlchk.toggled.connect(s.download_mode); v.addWidget(s.dlchk)
        v.addWidget(QLabel('Sleep timer and keyboard shortcuts are available from the player bar and shortcut settings below.'))
        shortcut_title = QLabel('Keyboard shortcuts'); shortcut_title.setObjectName('h2'); v.addSpacing(8); v.addWidget(shortcut_title)
        shortcut_names = [('toggle', 'Play / pause'), ('next', 'Next track'), ('previous', 'Previous track'), ('like', 'Like current track'), ('queue', 'Open queue'), ('search', 'Focus search')]
        shortcut_defaults = {'toggle': 'Space', 'next': 'Ctrl+Right', 'previous': 'Ctrl+Left', 'like': 'Ctrl+L', 'queue': 'Ctrl+Q', 'search': 'Ctrl+F'}
        for name, label in shortcut_names:
            row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addStretch(); edit = QKeySequenceEdit(QKeySequence(s.cfg.get('shortcuts', {}).get(name, shortcut_defaults[name]))); edit.setMaximumWidth(220)
            edit.keySequenceChanged.connect(lambda sequence, action=name: s.save_shortcut(action, sequence)); row.addWidget(edit); v.addLayout(row)
        v.addWidget(QLabel('Playback speed')); speed = ClickSlider(Qt.Horizontal); s.speed_slider = speed; speed.setRange(50, 200); speed.setFixedWidth(300); speed.setValue(int(s.cfg.get('playback_speed', 100))); speed.valueChanged.connect(s.playback_speed); v.addWidget(speed)
        fade_row = QHBoxLayout(); fade_row.addWidget(QLabel('Track transition fade')); s.fade_slider = ClickSlider(Qt.Horizontal); s.fade_slider.setRange(0, 5000); s.fade_slider.setSingleStep(250); s.fade_slider.setFixedWidth(260); s.fade_slider.setValue(int(s.cfg.get('transition_fade_ms', 0))); s.fade_slider.valueChanged.connect(s.set_transition_fade); fade_row.addWidget(s.fade_slider); v.addLayout(fade_row)
        c = QLabel('Output device'); c.setObjectName('h2'); v.addSpacing(8); v.addWidget(c)
        s.audio_device_combo = QComboBox(); s.audio_device_combo.addItem('System default', None); saved_device = s.cfg.get('audio_device', '')
        for device in QMediaDevices.audioOutputs():
            s.audio_device_combo.addItem(device.description(), device)
            if bytes(device.id()).decode('utf-8', 'ignore') == saved_device: s.audio_device_combo.setCurrentIndex(s.audio_device_combo.count() - 1)
        s.audio_device_combo.currentIndexChanged.connect(s.set_audio_device); v.addWidget(s.audio_device_combo, 0, Qt.AlignLeft)
        appearance = QLabel('Appearance and accessibility'); appearance.setObjectName('h2'); v.addSpacing(10); v.addWidget(appearance)
        theme_row = QHBoxLayout(); theme_row.addWidget(QLabel('App theme')); s.app_theme_combo = QComboBox(); s.app_theme_combo.addItems(['Dark', 'Light']); s.app_theme_combo.setCurrentText(s.cfg.get('app_theme', 'Dark')); s.app_theme_combo.currentTextChanged.connect(s.set_app_theme); theme_row.addWidget(s.app_theme_combo); theme_row.addStretch(); v.addLayout(theme_row)
        s.high_contrast_chk = QCheckBox('High contrast text and keyboard focus outlines'); s.high_contrast_chk.setChecked(s.cfg.get('high_contrast', False)); s.high_contrast_chk.toggled.connect(s.set_high_contrast); v.addWidget(s.high_contrast_chk)
        s.artwork_accent = QCheckBox('Pick the accent color from each song cover'); s.artwork_accent.setChecked(s.cfg.get('artwork_accent', False)); s.artwork_accent.toggled.connect(lambda on: (s.cfg.__setitem__('artwork_accent', on), save_cfg(s.cfg))); v.addWidget(s.artwork_accent)
        presetrow = QHBoxLayout(); presetrow.addWidget(QLabel('Layout preset')); s.layout_combo = QComboBox(); s.layout_combo.addItems(['Standard', 'Compact', 'Wide']); s.layout_combo.setCurrentText(s.cfg.get('layout_preset', 'Standard')); s.layout_combo.currentTextChanged.connect(s.layout_preset); presetrow.addWidget(s.layout_combo); presetrow.addStretch(); v.addLayout(presetrow)
        opacityrow = QHBoxLayout(); opacityrow.addWidget(QLabel('Window opacity')); s.opacity_slider = ClickSlider(Qt.Horizontal); s.opacity_slider.setRange(60, 100); s.opacity_slider.setFixedWidth(220); s.opacity_slider.setValue(int(s.cfg.get('window_opacity', 100))); s.opacity_slider.valueChanged.connect(s.set_window_opacity); opacityrow.addWidget(s.opacity_slider); v.addLayout(opacityrow)
        style_button = QPushButton('Edit custom Qt style sheet'); style_button.setObjectName('grey'); style_button.clicked.connect(s.open_qss_editor); v.addWidget(style_button, 0, Qt.AlignLeft)
        c = QLabel('Discord Rich Presence'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        d = QLabel('Optional. Create a Discord application and paste its application ID. When enabled, Bubble sends the current song and playback state to your local Discord client.'); d.setObjectName('dim'); d.setWordWrap(True); v.addWidget(d)
        s.discord_id = QLineEdit(s.cfg.get('discord_client_id', '')); s.discord_id.setPlaceholderText('Discord application ID'); s.discord_id.editingFinished.connect(s.save_discord_id); s.discord_id.setMaximumWidth(360); v.addWidget(s.discord_id)
        s.discord_chk = QCheckBox('Enable Discord Rich Presence'); s.discord_chk.setChecked(s.cfg.get('discord_presence', False)); s.discord_chk.toggled.connect(s.set_discord_presence); v.addWidget(s.discord_chk)
        c = QLabel('Plugins'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        plugin_note = QLabel('Add trusted Python plugins that contribute actions to the track menu. Plugins run locally and can access files as your user.'); plugin_note.setObjectName('dim'); plugin_note.setWordWrap(True); v.addWidget(plugin_note)
        plugins = QPushButton('Manage plugins'); plugins.setObjectName('grey'); plugins.clicked.connect(s.manage_plugins); v.addWidget(plugins, 0, Qt.AlignLeft)
        accentrow = QHBoxLayout(); accentrow.addWidget(QLabel('Accent hue')); s.accent_hue = ClickSlider(Qt.Horizontal); s.accent_hue.setRange(0, 359); s.accent_hue.setValue(QColor(s.cfg.get('accent_color', '#33d6e8')).hue() % 360); accentrow.addWidget(s.accent_hue, 1); v.addLayout(accentrow)
        intensityrow = QHBoxLayout(); intensityrow.addWidget(QLabel('Accent intensity')); s.accent_intensity = ClickSlider(Qt.Horizontal); s.accent_intensity.setRange(25, 100); s.accent_intensity.setValue(int(s.cfg.get('accent_intensity', 90))); intensityrow.addWidget(s.accent_intensity, 1); v.addLayout(intensityrow)
        s.accent_hue.valueChanged.connect(s.update_accent_setting); s.accent_intensity.valueChanged.connect(s.update_accent_setting)
        c = QLabel('Library tools'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        duplicate = QPushButton('Find possible duplicates'); duplicate.setObjectName('grey'); duplicate.clicked.connect(s.find_duplicates); v.addWidget(duplicate, 0, Qt.AlignLeft)
        repair = QPushButton('Repair missing songs / rescan folders'); repair.setObjectName('grey'); repair.clicked.connect(s.repair_library); v.addWidget(repair, 0, Qt.AlignLeft)
        sidebar_title = QLabel('Sidebar sections'); sidebar_title.setObjectName('h2'); v.addSpacing(8); v.addWidget(sidebar_title)
        sidebar_options = ((1, 'Library'), (2, 'Liked songs'), (3, 'Recently played'), (5, 'YouTube'), (6, 'Playlists'), (7, 'Albums'), (8, 'Artists'))
        s.sidebar_checks = {}
        for page, label in sidebar_options:
            check = QCheckBox(label); check.setChecked(s.cfg.get('sidebar_sections', {}).get(str(page), True)); check.toggled.connect(lambda on, p=page: s.toggle_sidebar_section(p, on)); v.addWidget(check); s.sidebar_checks[page] = check
        s.eqnote = QLabel('Use Edit audio from a track’s menu to trim a copy, apply a 10-band EQ, reverb, distortion, speed, and pitch. Playback speed below affects the current player.'); s.eqnote.setObjectName('dim'); s.eqnote.setWordWrap(True); v.addWidget(s.eqnote)
        s.visualizer_chk = QCheckBox('Show live audio visualizer'); s.visualizer_chk.setChecked(s.cfg.get('visualizer', True)); s.visualizer_chk.toggled.connect(lambda on: (s.cfg.__setitem__('visualizer', on), save_cfg(s.cfg), s.visualizer.setVisible(on))); v.addWidget(s.visualizer_chk)
        visualrow = QHBoxLayout(); visualrow.addWidget(QLabel('Visualizer style')); s.visualizer_combo = QComboBox(); s.visualizer_combo.addItems(['Bars', 'Mirror', 'Dots']); s.visualizer_combo.setCurrentText(s.cfg.get('visualizer_style', 'Bars')); s.visualizer_combo.currentTextChanged.connect(s.visualizer_style); visualrow.addWidget(s.visualizer_combo); visualrow.addStretch(); v.addLayout(visualrow)
        privacy = QLabel('Privacy: Bubble has no analytics or telemetry. It contacts music providers for content you play or import and for requested cover art or lyrics. Discord Rich Presence is opt-in. Provider access, catalog availability, and advertisements are controlled by each music service.'); privacy.setObjectName('dim'); privacy.setWordWrap(True); v.addWidget(privacy)
        s.chk = QCheckBox('Look up missing lyrics online (LRCLIB, plus Genius if you add a token below)'); s.chk.setChecked(s.cfg.get('lyrics_online', True)); s.chk.toggled.connect(lambda x: s.cfg.__setitem__('lyrics_online', x) or save_cfg(s.cfg)); v.addWidget(s.chk)
        v.addWidget(QLabel('Bounciness (lower = calmer)')); bs = ClickSlider(Qt.Horizontal); s.bounce_slider = bs; bs.setRange(0, 100); bs.setFixedWidth(260); bs.setValue(int((.5 - PH['C']) / .30 * 100)); bs.valueChanged.connect(s.bounce); v.addWidget(bs)
        s.add_genius(v); s.add_bg(v)
        c = QLabel('Storage'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        restore = QPushButton('Restore settings backup'); restore.setObjectName('grey'); restore.clicked.connect(s.restore_settings_backup); v.addWidget(restore, 0, Qt.AlignLeft)
        paths = QLabel(f'Songs: {SONGS_DIR}\nSettings and cache: {DATA_DIR}'); paths.setObjectName('dim'); paths.setWordWrap(True); v.addWidget(paths)
        row = QHBoxLayout(); open_songs = QPushButton('Open songs folder'); open_songs.clicked.connect(s.open_songs_folder); row.addWidget(open_songs)
        open_data = QPushButton('Open data folder'); open_data.clicked.connect(s.open_data_folder); row.addWidget(open_data); row.addStretch(); v.addLayout(row)
        c = QLabel('Music folders'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c); s.fl = QLabel(); s.fl.setObjectName('dim'); s.fl.setWordWrap(True); v.addWidget(s.fl)
        b = QPushButton('Add folder'); b.clicked.connect(s.add_folder); v.addWidget(b, 0, Qt.AlignLeft)
        c = QLabel('Library'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        reset = QPushButton('Reset all songs in library'); reset.setObjectName('grey'); reset.clicked.connect(s.reset_library); v.addWidget(reset, 0, Qt.AlignLeft)
        c = QLabel('Preferences'); c.setObjectName('h2'); v.addSpacing(10); v.addWidget(c)
        reset_prefs = QPushButton('Reset settings to defaults'); reset_prefs.setObjectName('grey'); reset_prefs.clicked.connect(s.reset_settings); v.addWidget(reset_prefs, 0, Qt.AlignLeft)
        v.addStretch(); s.fl_upd(); sc.setWidget(w); return sc

def main():
    global B
    if '--spotdl-worker' in sys.argv:
        from spotdl import console_entry_point
        worker_at = sys.argv.index('--spotdl-worker')
        sys.argv = [sys.argv[0], *sys.argv[worker_at + 1:]]
        console_entry_point()
        return 0
    cfg = load_cfg()
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv); app.setStyle('Fusion'); app.setFont(QFont('Segoe UI', 10)); app.setStyleSheet(QSS)
    apply_runtime_preferences(cfg, app)
    pal = QPalette()
    for r, c in ((QPalette.Window, '#0a0a0a'), (QPalette.WindowText, '#fff'), (QPalette.Base, '#0d0d0d'), (QPalette.AlternateBase, '#161616'), (QPalette.Text, '#fff'),
                 (QPalette.Button, '#161616'), (QPalette.ButtonText, '#fff'), (QPalette.Highlight, ACC), (QPalette.HighlightedText, '#000')): pal.setColor(r, QColor(c))
    app.setPalette(pal)
    app.setWindowIcon(QIcon(asset('logo.png')))
    apply_runtime_preferences(cfg, app)
    B = Bridge(); w = Win(); w.show(); return app.exec()
