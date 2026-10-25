#!/usr/bin/env python3
"""Exercise real offline CPython with getrandom unavailable; no physical NV IO.

sudo python3 boot/tests/nv-offline-runtime.py --rootfs <registered OpenWrt base>
Uses an overlay over the read-only input, with nine tiny synthetic NV files.
"""
import argparse
import ctypes
import errno
import importlib.util
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

TOP = Path(__file__).resolve().parents[2]


def unavailable_getrandom():
    # Applied to the test child only. ENOSYS forces CPython's normal /dev/urandom
    # fallback without changing the host's entropy or Python hash seed policy.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    filters = (Filter * 4)(Filter(0x20, 0, 0, 0), Filter(0x15, 0, 1, 318),
                           Filter(0x06, 0, 0, 0x50000 | errno.ENOSYS),
                           Filter(0x06, 0, 0, 0x7fff0000))
    program = Program(4, filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot install child-only seccomp fixture')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() or platform.machine() != 'x86_64':
        raise SystemExit('Run as root on the local x86_64 Linux/WSL test host')
    source = TOP/'openwrt/luci-app-t551m/root/usr/lib/e5/nv_persistence.py'
    spec = importlib.util.spec_from_file_location('nv_fixture', source)
    nv = importlib.util.module_from_spec(spec); spec.loader.exec_module(nv)
    with tempfile.TemporaryDirectory(prefix='e5-offline-nv-runtime-') as tmp:
        tmp = Path(tmp); root = tmp/'root'; upper = tmp/'upper'; work = tmp/'work'
        for path in (root, upper, work): path.mkdir()
        subprocess.run(['mount', '-t', 'overlay', 'overlay', '-o',
                        f'lowerdir={args.rootfs.resolve()},upperdir={upper},workdir={work}', root], check=True)
        try:
            assert (root/'dev').is_dir() and not (root/'dev/urandom').exists()
            store = root/'opt/e5/nv'; store.mkdir(parents=True, exist_ok=True)
            (root/'etc/e5/device-profile').write_text('e5\n')
            data = struct.pack('<4I', 0x4e56, 2, 0xfffe, 1).ljust(512, b'\0') + b'\1\0'
            for name in nv.NAMES:
                (store/name).write_bytes(data if name.startswith(('nr_fixnv', 'nr_runtimenv')) else b'opaque')
            (store/'factory-sha256.json').write_text(json.dumps({n:nv.digest(store/n) for n in nv.NAMES}))
            subprocess.run(['mount', '-o', 'remount,ro', root], check=True)
            command = ['chroot', str(root), '/usr/bin/python3', '-c', 'print("runtime ready")']
            broken = subprocess.run(command, capture_output=True, preexec_fn=unavailable_getrandom, timeout=20)
            # QEMU itself may need /dev/urandom before it can launch CPython;
            # on native ARM the failure is CPython's hash-seed initialization.
            assert broken.returncode and any(message in broken.stderr for message in
                (b'_Py_HashRandomization_Init', b'cannot initialize crypto: No /dev/urandom')), broken.stderr
            print('Confirmed old path: offline runtime cannot obtain randomness before NV code executes', flush=True)
            helper = (TOP/'boot/nv-preserve.sh').read_text().replace('/etc/nv-persistence.py', str(source))
            helper = helper.replace('/run/nv-preserve.err', str(tmp/'nv-preserve.err'))
            archive = tmp/'preserved.tar'
            fixed = subprocess.run(['busybox', 'ash'], input=helper+f'\nnv_archive_offline "{root}" "{archive}"\n',
                                   text=True, capture_output=True, preexec_fn=unavailable_getrandom, timeout=30)
            assert fixed.returncode == 0, fixed.stderr
            assert archive.is_file() and not os.path.ismount(root/'dev')
            print('Fixed path: real read-only chroot NV archive succeeds; /dev mount released', flush=True)
            subprocess.run(['mount', '-o', 'remount,rw', root], check=True)
            restored = subprocess.run(['busybox', 'ash'], input=helper+f'\nnv_restore_offline "{root}" "{archive}"\n',
                                      text=True, capture_output=True, preexec_fn=unavailable_getrandom, timeout=30)
            assert restored.returncode == 0, restored.stderr
            assert not os.path.ismount(root/'dev')
            assert len(list((root/'etc/e5-nv/backups').glob('update-*'))) == 1
            print('Fixed path: verification and backup (secrets.token_hex) succeed; mounts released', flush=True)
            (store/'nr_fixnv1_a').write_bytes(b'bad NV header')
            subprocess.run(['mount', '-o', 'remount,ro', root], check=True)
            rejected = subprocess.run(['busybox', 'ash'], input=helper+f'\nnv_archive_offline "{root}" "{tmp}/bad.tar"\n',
                                      text=True, capture_output=True, preexec_fn=unavailable_getrandom, timeout=30)
            assert rejected.returncode and 'nv_invalid_header' in rejected.stderr, rejected.stderr
            assert not os.path.ismount(root/'dev') and not (tmp/'bad.tar.part').exists()
            print('Invalid NV still rejected; failed invocation releases /dev and removes incomplete archive', flush=True)
        finally:
            if os.path.ismount(root/'dev'): subprocess.run(['umount', root/'dev'], check=True)
            subprocess.run(['umount', root], check=True)


if __name__ == '__main__': main()
