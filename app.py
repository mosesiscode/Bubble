"""Bubble Player launcher retained for direct runs and PyInstaller builds."""

import os
import sys


SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

from bubble.application import main


if __name__ == '__main__':
    raise SystemExit(main())
