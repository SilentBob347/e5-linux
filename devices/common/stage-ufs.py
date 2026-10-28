#!/usr/bin/env python3
"""Stage the registered, source-matched READ-DESCRIPTOR helper for UFS roots."""
import hashlib
import json
from pathlib import Path
import runpy

TOP = Path(__file__).resolve().parents[2]


def stage(root, helper=None):
    root = Path(root)
    if root.resolve() == Path('/') or (root/'etc/e5/storage-kind').read_text().strip() != 'ufs':
        raise ValueError('Expected an offline UFS profile root')
    if helper is None:
        config = json.loads((TOP/'tools/build-layout.json').read_text())
        helper = Path(config['ufs_identity_helper'].format(repo=TOP))
    helper = Path(helper)
    receipt = json.loads(helper.with_suffix('.build.json').read_text())
    data = helper.read_bytes()
    if (receipt.get('format'), receipt.get('kind'), receipt.get('static_arm64')) != (1, 'ufs-descriptor-v1', True):
        raise ValueError('Unrecognized UFS identity helper build')
    if (receipt['sha256'] != hashlib.sha256(data).hexdigest() or receipt['bytes'] != len(data) or
            receipt['source_sha256'] != hashlib.sha256((TOP/'tools/ufs-id.c').read_bytes()).hexdigest()):
        raise ValueError('UFS identity helper is stale or changed; rebuild the registered input')
    runpy.run_path(str(TOP/'tools/build-ufs-id.py'))['check_static_arm64'](data)
    target = root/'usr/libexec/e5-ufs-id'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError('Unexpected UFS identity helper destination symlink')
    target.write_bytes(data)
    target.chmod(0o755)
