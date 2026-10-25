#!/usr/bin/env python3
"""Real BLKROSET/readback recovery on disposable synthetic loop devices.

Run as root under Linux/WSL. Never accepts a device argument or physical NV.
"""
import fcntl
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('nv_writeback_fixture',TOP/'openwrt/tests/nv-writeback.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
nv,wb=fixture.nv,fixture.wb


def ro(device,value=None):
    with device.open('rb') as stream:
        if value is not None:fcntl.ioctl(stream,0x125d,struct.pack('i',value))
        return struct.unpack('i',fcntl.ioctl(stream,0x125e,bytes(4)))[0]


def main():
    if os.geteuid()!=0:raise SystemExit('Run as root; only newly allocated synthetic loops are used.')
    case=fixture.Fixture();case.setUp();loops=[]
    try:
        names=('nr_fixnv1_b','nr_fixnv2_b','nr_runtimenv1','nr_runtimenv2','calinv')
        # A trusted original snapshot can restore an opaque calibration image.
        # All of these bytes are synthetic; no physical NV is accepted here.
        case.devices['calinv'].write_bytes(b'new calibration'.ljust(4096,b'\0'))
        for name in names:
            backing=case.devices[name]
            device=Path(subprocess.check_output(['losetup','--find','--show',str(backing)],text=True).strip())
            actual=Path('/sys/class/block')/device.name/'loop/backing_file'
            if Path(actual.read_text().strip()).resolve()!=backing.resolve():raise RuntimeError('Loop ownership mismatch')
            loops.append(device);case.devices[name]=device;assert ro(device,1)==1
        before={n:nv.digest(p) for n,p in case.devices.items()}
        case.changed()
        for name in ('nr_runtimenv1','nr_runtimenv2'):(case.store/name).write_bytes(fixture.runtime_image(6))
        outcome=wb.writeback(case.manager,case.saved(),writer=wb.PairWriter())
        assert outcome['ok'] and all(ro(p)==1 for p in loops)
        assert all(nv.digest(case.devices[n])==h for n,h in before.items() if n not in names)
        assert all(fixture.FixedNV.read(p).imeis()['sim1']=='111111111111111' for p in loops[:2])
        for name in names:assert case.devices[name].read_bytes()==(case.store/name).read_bytes()
        # The same real writer must restore RO on a failed write as well.
        backup=case.root/outcome['backup'].lstrip('/')
        with patch.object(wb.os,'write',side_effect=OSError('synthetic write failure')):
            try:wb.PairWriter().write(backup/'source/nr_fixnv1_b',loops[0],before['nr_fixnv1_b'])
            except OSError:pass
            else:raise AssertionError('Injected failure did not occur')
        assert ro(loops[0])==1
        # Restore the fixture's original snapshots through actual block writes.
        for name,device in zip(names,loops):
            wb.PairWriter().write(backup/'source'/name,device,before[name]);assert ro(device)==1
        assert all(nv.digest(p)==before[n] for n,p in case.devices.items())
        print('PASS: five real loops: fixed/runtime/opaque-provenance full writes, gzip readback, typed validation including erased runtime, BLKROSET on success/failure and old-image restoration; no physical device touched')
    finally:
        for device in reversed(loops):
            subprocess.run(['losetup','--detach',str(device)],check=True)
        case.doCleanups()


if __name__=='__main__':main()
