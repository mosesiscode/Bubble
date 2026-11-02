"""Small manager for user-selected Python plugins."""

import os
import shutil

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout

from bubble.services.plugin_host import PLUGIN_DIR


class PluginManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bubble plugins'); self.resize(560, 430)
        root = QVBoxLayout(self)
        warning = QLabel('Plugins are Python programs and can access files and the network as your user. Only install plugins from sources you trust. Plugins run when Bubble starts.'); warning.setWordWrap(True); root.addWidget(warning)
        self.list = QListWidget(); root.addWidget(self.list, 1)
        self.refresh()
        row = QHBoxLayout(); add = QPushButton('Add Python plugin…'); add.clicked.connect(self.add_plugin); row.addWidget(add)
        remove = QPushButton('Remove selected'); remove.setObjectName('grey'); remove.clicked.connect(self.remove_plugin); row.addWidget(remove)
        done = QPushButton('Done'); done.clicked.connect(self.accept); row.addWidget(done); root.addLayout(row)

    def refresh(self):
        os.makedirs(PLUGIN_DIR, exist_ok=True); self.list.clear()
        for filename in sorted(os.listdir(PLUGIN_DIR), key=str.casefold):
            if filename.lower().endswith('.py'): self.list.addItem(filename)

    def add_plugin(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a Bubble Python plugin', '', 'Python plugins (*.py)')
        if not path: return
        if QMessageBox.question(self, 'Trust this plugin?', 'This Python plugin can run code as your Windows user. Install and enable it?') != QMessageBox.Yes: return
        os.makedirs(PLUGIN_DIR, exist_ok=True); name = os.path.basename(path); destination = os.path.join(PLUGIN_DIR, name)
        if os.path.exists(destination):
            QMessageBox.warning(self, 'Plugin already installed', 'Remove the existing plugin first, then add its replacement.'); return
        try: shutil.copy2(path, destination)
        except OSError as exc: QMessageBox.warning(self, 'Plugin install failed', str(exc)); return
        self.refresh()

    def remove_plugin(self):
        item = self.list.currentItem()
        if not item: return
        path = os.path.join(PLUGIN_DIR, item.text())
        if QMessageBox.question(self, 'Remove plugin', f'Remove {item.text()} from Bubble?') == QMessageBox.Yes:
            try: os.remove(path)
            except OSError as exc: QMessageBox.warning(self, 'Plugin removal failed', str(exc))
            self.refresh()
