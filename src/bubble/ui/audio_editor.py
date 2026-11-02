"""Non-destructive trim and effect rendering for local audio files."""

import os

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class AudioEditorDialog(QDialog):
    rendered = Signal(str)

    def __init__(self, source, output, duration_ms, parent=None):
        super().__init__(parent)
        self.source = source
        self.output = output
        self.duration_s = max(.1, duration_ms / 1000)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.setWindowTitle('Trim and process audio')
        self.resize(700, 680)
        root = QVBoxLayout(self)
        note = QLabel('This creates a processed copy and leaves the original untouched. FLAC/WAV output preserves lossless audio when the source is lossless; converting MP3 cannot restore detail that was already lost.'); note.setWordWrap(True); root.addWidget(note)

        trim = QFormLayout()
        self.start = QDoubleSpinBox(); self.start.setRange(0, self.duration_s); self.start.setSuffix(' sec'); self.start.setDecimals(2)
        self.end = QDoubleSpinBox(); self.end.setRange(.1, self.duration_s); self.end.setValue(self.duration_s); self.end.setSuffix(' sec'); self.end.setDecimals(2)
        trim.addRow('Start', self.start); trim.addRow('End', self.end); root.addLayout(trim)

        root.addWidget(QLabel('10-band equalizer (dB)'))
        grid = QGridLayout(); self.bands = []
        for column, frequency in enumerate(('31', '62', '125', '250', '500', '1k', '2k', '4k', '8k', '16k')):
            cell = QWidget(); col = QVBoxLayout(cell); col.setContentsMargins(2, 0, 2, 0)
            label = QLabel(frequency); label.setAlignment(Qt.AlignCenter)
            slider = QSlider(Qt.Vertical); slider.setRange(-12, 12); slider.setValue(0); slider.setTickInterval(6); slider.setTickPosition(QSlider.TicksBothSides); slider.setMinimumHeight(125)
            value = QLabel('0'); value.setAlignment(Qt.AlignCenter); slider.valueChanged.connect(lambda v, out=value: out.setText(str(v)))
            col.addWidget(label); col.addWidget(slider, 1, Qt.AlignHCenter); col.addWidget(value); grid.addWidget(cell, 0, column); self.bands.append((int(frequency) if frequency.isdigit() else int(frequency[:-1]) * 1000, slider))
        root.addLayout(grid)

        quick = QFormLayout(); self.quick_eq = []; self.applying_preset = False
        self.preset = QComboBox(); self.preset.addItems(['Custom', 'Flat', 'Bass boost', 'Vocal clarity', 'Treble lift'])
        self.preset.currentTextChanged.connect(self._apply_preset); quick.addRow('Quick EQ preset', self.preset)
        for label in ('Bass', 'Mid', 'Treble'):
            slider = QSlider(Qt.Horizontal); slider.setRange(-12, 12); slider.setValue(0); slider.setTickInterval(3); slider.setTickPosition(QSlider.TicksBelow)
            value = QLabel('0 dB'); slider.valueChanged.connect(lambda v, out=value: out.setText(f'{v:+d} dB'))
            slider.valueChanged.connect(lambda _v: self.preset.setCurrentText('Custom') if not self.applying_preset and self.preset.currentText() != 'Custom' else None)
            line = QHBoxLayout(); line.addWidget(slider, 1); line.addWidget(value); quick.addRow(label, line); self.quick_eq.append(slider)
        root.addLayout(quick)

        effects = QFormLayout()
        self.reverb = QDoubleSpinBox(); self.reverb.setRange(0, 0.8); self.reverb.setSingleStep(.1); self.reverb.setSuffix(' mix'); effects.addRow('Reverb', self.reverb)
        self.distortion = QDoubleSpinBox(); self.distortion.setRange(0, 1); self.distortion.setSingleStep(.1); self.distortion.setSuffix(' amount'); effects.addRow('Distortion', self.distortion)
        self.speed = QDoubleSpinBox(); self.speed.setRange(.5, 2); self.speed.setValue(1); self.speed.setSingleStep(.05); self.speed.setSuffix('×'); effects.addRow('Speed', self.speed)
        self.pitch = QDoubleSpinBox(); self.pitch.setRange(-12, 12); self.pitch.setSuffix(' semitones'); effects.addRow('Pitch', self.pitch)
        root.addLayout(effects)

        self.status = QLabel('Ready to render'); root.addWidget(self.status)
        buttons = QHBoxLayout(); buttons.addStretch(); self.cancel_button = QPushButton('Close'); self.cancel_button.setObjectName('grey'); self.cancel_button.clicked.connect(self.reject); buttons.addWidget(self.cancel_button)
        self.render_button = QPushButton('Render copy'); self.render_button.clicked.connect(self.render); buttons.addWidget(self.render_button); root.addLayout(buttons)

    def render(self):
        if self.end.value() <= self.start.value():
            QMessageBox.warning(self, 'Invalid trim range', 'The end time must be after the start time.')
            return
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            QMessageBox.warning(self, 'FFmpeg unavailable', 'The bundled audio renderer is unavailable. Rebuild Bubble after installing its requirements.')
            return
        filters = []
        for frequency, slider in zip((100, 1000, 8000), self.quick_eq):
            gain = slider.value()
            if gain: filters.append(f'equalizer=f={frequency}:width_type=o:width=1:g={gain}')
        for frequency, slider in self.bands:
            gain = slider.value()
            if gain:
                filters.append(f'equalizer=f={frequency}:width_type=o:width=1:g={gain}')
        reverb = self.reverb.value()
        if reverb: filters.append(f'aecho=0.8:0.88:60:0.35*{reverb:.2f}')
        distortion = self.distortion.value()
        if distortion: filters.append(f'asoftclip=type=hard:threshold={max(.1, 1 - .8 * distortion):.3f}')
        speed = self.speed.value()
        if abs(speed - 1) > .001: filters.append(f'atempo={speed:.3f}')
        semitones = self.pitch.value()
        if semitones:
            ratio = 2 ** (semitones / 12)
            filters.extend((f'asetrate={round(44100 * ratio)}', 'aresample=44100', f'atempo={1 / ratio:.6f}'))

        args = ['-hide_banner', '-y', '-ss', f'{self.start.value():.3f}', '-to', f'{self.end.value():.3f}', '-i', self.source]
        if filters: args.extend(('-af', ','.join(filters)))
        args.extend(('-map_metadata', '0'))
        ext = os.path.splitext(self.output)[1].lower()
        codec = {'.flac': 'flac', '.wav': 'pcm_s24le', '.mp3': 'libmp3lame', '.ogg': 'libvorbis', '.m4a': 'aac'}.get(ext)
        if codec: args.extend(('-c:a', codec))
        if ext == '.mp3': args.extend(('-q:a', '2'))
        elif ext == '.ogg': args.extend(('-q:a', '6'))
        elif ext == '.m4a': args.extend(('-b:a', '256k'))
        args.append(self.output)
        self.render_button.setEnabled(False); self.status.setText('Rendering…'); self.cancel_button.setText('Cancel render')
        self.cancel_button.clicked.disconnect(); self.cancel_button.clicked.connect(self.process.kill)
        self.process.start(ffmpeg, args)

    def _apply_preset(self, name):
        presets = {'Custom': None, 'Flat': (0, 0, 0), 'Bass boost': (5, 0, 1), 'Vocal clarity': (0, 3, 2), 'Treble lift': (0, 1, 5)}
        values = presets.get(name)
        if values is None: return
        self.applying_preset = True
        for slider, value in zip(self.quick_eq, values):
            slider.setValue(value)
        self.applying_preset = False

    def _finished(self, code, _status):
        self.render_button.setEnabled(True); self.cancel_button.setText('Close')
        self.cancel_button.clicked.disconnect(); self.cancel_button.clicked.connect(self.reject)
        if code == 0 and os.path.isfile(self.output):
            self.status.setText('Render complete'); self.rendered.emit(self.output)
        else:
            self.status.setText('Render failed; the original file is unchanged.')
