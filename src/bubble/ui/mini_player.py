"""Compact always-on-top playback window."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class MiniPlayerDialog(QDialog):
    play_pause = Signal()
    previous = Signal()
    next = Signal()
    restore = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('Bubble Mini Player'); self.setFixedSize(390, 112)
        root = QHBoxLayout(self); root.setContentsMargins(12, 10, 12, 10); root.setSpacing(10)
        self.cover = QLabel(); self.cover.setFixedSize(72, 72); self.cover.setAlignment(Qt.AlignCenter); root.addWidget(self.cover)
        info = QVBoxLayout(); self.title = QLabel('No track playing'); self.title.setStyleSheet('font-weight:700;font-size:14px'); self.title.setWordWrap(True); self.artist = QLabel('Bubble Player'); self.artist.setObjectName('dim'); info.addWidget(self.title); info.addWidget(self.artist); info.addStretch(); root.addLayout(info, 1)
        controls = QHBoxLayout()
        for label, signal in (('‹', self.previous), ('Play', self.play_pause), ('›', self.next)):
            button = QPushButton(label); button.setFixedWidth(48); button.clicked.connect(lambda _checked=False, target=signal: target.emit()); controls.addWidget(button)
            if signal is self.play_pause: self.play_button = button
        restore = QPushButton('Open'); restore.clicked.connect(self.restore.emit); controls.addWidget(restore); root.addLayout(controls)

    def set_track(self, title, artist, cover=None, playing=False):
        self.title.setText(title or 'No track playing'); self.artist.setText(artist or 'Bubble Player')
        self.cover.setPixmap(cover.scaled(72, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation) if isinstance(cover, QPixmap) else QPixmap())
        self.play_button.setText('Pause' if playing else 'Play')
