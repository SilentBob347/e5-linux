#!/usr/bin/env python3
"""Stage T512N identity and shared handheld features into an offline root."""
import argparse
from pathlib import Path
import runpy
TOP = Path(__file__).resolve().parents[2]


def stage(root):
    runpy.run_path(str(TOP / 'devices/common/handheld-stage.py'))['stage'](
        root, profile='t512n', model='T512N')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    stage(parser.parse_args().root)
