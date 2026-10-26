#!/usr/bin/env python3
"""Root/WSL test: actual copy-on-write mount, private indexes and lower guards."""
from pathlib import Path
import os
import runpy
import subprocess
import sys
import tempfile

if sys.platform != 'linux' or os.geteuid() != 0:
    print('SKIP: actual overlayfs isolation test requires Linux root')
    raise SystemExit(0)

api=runpy.run_path(str(Path(__file__).resolve().parents[1]/'build-profile-kernel.py'))


def git(path,*args):
    return subprocess.check_output(['git','-C',str(path),*args])


with tempfile.TemporaryDirectory(prefix='e5-kernel-overlay-') as temp:
    workspace=Path(temp);lower=workspace/'lower';lower.mkdir()
    git(lower,'init','-q');git(lower,'config','user.name','Overlay test')
    git(lower,'config','user.email','overlay@example.invalid')
    (lower/'tracked.c').write_text('stock\n');(lower/'.gitignore').write_text('ignored\n')
    git(lower,'add','.');git(lower,'commit','-qm','fixture')
    revision=git(lower,'rev-parse','HEAD').decode().strip()
    (lower/'tracked.c').write_text('donor\n');(lower/'added.c').write_text('donor only\n')
    (lower/'ignored').write_text('cached output\n')
    before=api['inventory'](lower)[0]
    with api['source_view'](workspace,lower,'e5',revision) as view:
        assert (view/'tracked.c').read_text()=='stock\n'
        assert not (view/'added.c').exists() and not (view/'ignored').exists()
        (view/'tracked.c').write_text('e5 patch\n')
        (view/'own.c').write_text('private\n')
    assert api['inventory'](lower)[0]==before
    git(lower,'config','core.abbrev','20')
    assert api['inventory'](lower)[0]==before
    with api['source_view'](workspace,lower,'e5',revision) as view:
        assert (view/'tracked.c').read_text()=='e5 patch\n'
        assert (view/'own.c').read_text()=='private\n'
    with api['source_view'](workspace,lower,'m8',revision) as view:
        assert (view/'tracked.c').read_text()=='stock\n' and not (view/'own.c').exists()
    assert api['inventory'](lower)[0]==before
    (lower/'tracked.c').write_text('lower changed\n')
    try:
        with api['source_view'](workspace,lower,'e5',revision):
            raise AssertionError('changed lower was accepted')
    except ValueError as error:
        assert 'Lower source changed' in str(error)
    # Existing private files/whiteouts fully hide these donor changes. An
    # explicit audit may refresh registration without changing board sources.
    api['review_shadowed_lower'](workspace,lower,'e5',revision)
    with api['source_view'](workspace,lower,'e5',revision) as view:
        assert (view/'tracked.c').read_text()=='e5 patch\n'
        assert not (view/'added.c').exists()
    marker=workspace/'kernel-views/e5/owner.json'
    before_marker=marker.read_bytes()
    (lower/'new-unshadowed.c').write_text('new donor input\n')
    try:
        api['review_shadowed_lower'](workspace,lower,'e5',revision)
        raise AssertionError('unshadowed change was accepted')
    except ValueError as error:
        assert 'Unshadowed donor change' in str(error)
    assert marker.read_bytes()==before_marker
print('PASS: pristine view, private patches/indexes, unchanged donor, remount and changed-lower rejection')
