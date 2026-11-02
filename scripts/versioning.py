"""Persistent semantic patch versioning for packaged Bubble builds."""
import re
import sys
import platform
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / 'last-built-version.txt'
INITIAL_VERSION = '1.0.0'


def parse(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+', value.strip()):
        raise ValueError(f'Invalid version: {value!r}; expected MAJOR.MINOR.PATCH')
    return tuple(int(part) for part in value.strip().split('.'))


def read_last():
    if not VERSION_FILE.exists():
        return INITIAL_VERSION
    value = VERSION_FILE.read_text(encoding='utf-8').strip()
    parse(value)
    return value


def next_version():
    major, minor, patch = parse(read_last())
    return f'{major}.{minor}.{patch + 1}'


def record(value):
    parse(value)
    if parse(value) <= parse(read_last()):
        raise ValueError('The version to record must be newer than the last successful build')
    VERSION_FILE.write_text(value + '\n', encoding='utf-8')


def target():
    system = platform.system().lower()
    name = {'windows': 'win', 'darwin': 'macos', 'linux': 'linux'}.get(system, system)
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('arm64', 'aarch64') else 'x64' if machine in ('amd64', 'x86_64', 'x64') else machine
    return f'{name}-{arch}'


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'next':
        print(next_version())
    elif len(sys.argv) == 2 and sys.argv[1] == 'target':
        print(target())
    elif len(sys.argv) == 3 and sys.argv[1] == 'record':
        record(sys.argv[2])
    else:
        raise SystemExit('Usage: versioning.py next | target | record MAJOR.MINOR.PATCH')
