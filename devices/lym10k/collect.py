#!/usr/bin/env python3
"""Read verified LYM boot recovery inputs; never writes partitions or reboots."""
import argparse
import json
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]
sys.path.insert(0, str(TOP / 'installer'))
from backend.transport import Adb


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runpy.run_path(str(TOP / 'devices/common/stock-backup.py'))['collect'](
        Adb(TOP, args.serial), args.out,
        json.loads((HERE / 'profile.json').read_text(encoding='utf-8')))
