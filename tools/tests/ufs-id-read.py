#!/usr/bin/env python3
"""Native UFS request/response contract test; never opens a hardware device."""
from pathlib import Path
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix='e5-ufs-read-test-') as directory:
    executable=Path(directory)/'read-test'
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                    str(Path(__file__).with_suffix('.c')),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
