"""User-installed Bubble Python plugin loader."""

import importlib.util
import os
import re

from bubble.config import DATA_DIR


PLUGIN_DIR = os.path.join(DATA_DIR, 'plugins')


class PluginAPI:
    def __init__(self):
        self.actions = []

    def add_track_action(self, label, callback):
        """Register a context-menu action. Callback receives (track, app_window)."""
        if callable(callback) and str(label).strip():
            self.actions.append((str(label).strip()[:64], callback))


def load_plugins():
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    api = PluginAPI()
    for filename in sorted(os.listdir(PLUGIN_DIR), key=str.casefold):
        if not filename.lower().endswith('.py') or filename.startswith('_'):
            continue
        path = os.path.join(PLUGIN_DIR, filename)
        module_name = 'bubble_user_plugin_' + re.sub(r'\W+', '_', filename)
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader: continue
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            register = getattr(module, 'register', None)
            if callable(register): register(api)
        except Exception:
            continue
    return api
