#!/usr/bin/env python3
"""Reuse the 41S complete Image/module builder, with this board's preparation."""
from pathlib import Path
import runpy

if __name__=='__main__':
    here=Path(__file__).resolve().parent
    runpy.run_path(str(here.parent/'yuanhang41s/build-kernel.py'))['main'](
        profile='changxing60',here=here)
