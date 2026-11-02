"""User data paths, persistent settings, and installer shortcuts."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date


EXT = ('.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav', '.wma', '.webm', '.mp4')
APPDATA = os.environ.get('APPDATA', os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming'))
BUBBLE_HOME = os.path.join(APPDATA, 'Bubble')
DATA_DIR = os.path.join(BUBBLE_HOME, 'data')
SONGS_DIR = os.path.join(BUBBLE_HOME, 'songs')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SONGS_DIR, exist_ok=True)
CFG = os.path.join(DATA_DIR, 'bubbleplayer.json')
LEGACY_CFG = os.path.join(os.path.expanduser('~'), '.bubbleplayer.json')
UA = {'User-Agent': 'BubblePlayer/1.0'}


def load_cfg():
    try:
        with open(CFG, encoding='utf-8') as source:
            return json.load(source)
    except Exception:
        try:
            with open(LEGACY_CFG, encoding='utf-8') as source:
                config = json.load(source)
            save_cfg(config)
            return config
        except Exception:
            return {}


def save_cfg(config):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.isfile(CFG) and os.path.getsize(CFG) > 0:
            backup_dir = os.path.join(DATA_DIR, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            backup = os.path.join(backup_dir, f'bubbleplayer-{date.today().isoformat()}.json')
            if not os.path.exists(backup):
                shutil.copy2(CFG, backup)
            backups = sorted((os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith('.json')), key=os.path.getmtime, reverse=True)
            for old in backups[14:]:
                os.remove(old)
        fd, temp_path = tempfile.mkstemp(prefix='bubble-settings-', suffix='.tmp', dir=DATA_DIR)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as target:
                json.dump(config, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, CFG)
        finally:
            if os.path.exists(temp_path): os.remove(temp_path)
    except Exception:
        pass


def restore_cfg_backup(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding='utf-8') as source:
            json.load(source)
        # Save today's current state first, then put the selected snapshot in place.
        save_cfg(load_cfg())
        os.makedirs(DATA_DIR, exist_ok=True)
        shutil.copy2(path, CFG)
        return True
    except Exception:
        return False


def create_windows_shortcuts(desktop=True, start_menu=True):
    if os.name != 'nt':
        return False
    exe = sys.executable
    args = '' if getattr(sys, 'frozen', False) else '"' + os.path.abspath(sys.argv[0]) + '"'
    work = os.path.dirname(exe)
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = [
        "$shell = New-Object -ComObject WScript.Shell",
        "$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'Bubble'",
        "New-Item -ItemType Directory -Force -Path $programs | Out-Null",
        f"$exe = {quote(exe)}; $launchArgs = {quote(args)}; $work = {quote(work)}",
        "$targets = @()",
        "if ($env:BUBBLE_START_SHORTCUT -eq '1') { $targets += Join-Path $programs 'Bubble Player.lnk' } else { Remove-Item -LiteralPath (Join-Path $programs 'Bubble Player.lnk') -Force -ErrorAction SilentlyContinue }",
        "if ($env:BUBBLE_DESKTOP_SHORTCUT -eq '1') { $targets += Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Bubble Player.lnk' } else { Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Bubble Player.lnk') -Force -ErrorAction SilentlyContinue }",
        "foreach ($target in $targets) { $link = $shell.CreateShortcut($target); $link.TargetPath = $exe; $link.Arguments = $launchArgs; $link.WorkingDirectory = $work; $link.IconLocation = $exe + ',0'; $link.Save() }",
    ]
    env = os.environ.copy()
    env['BUBBLE_DESKTOP_SHORTCUT'] = '1' if desktop else '0'
    env['BUBBLE_START_SHORTCUT'] = '1' if start_menu else '0'
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', '\n'.join(script)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=20,
            env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return result.returncode == 0
    except Exception:
        return False
