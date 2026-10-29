#!/usr/bin/env python3
"""Collect only this P720S20's vendor runtime/firmware, never raw NV or an install."""
import argparse
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import tarfile

TOP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOP / 'installer'))
from backend.state import DeviceLock, app_directory, atomic_json, sha
from backend.transport import Adb


def enrich_audio(adb, destination):
    destination = Path(destination)
    target = destination / 'device-files.tar'
    with tarfile.open(target, 'a') as archive:
        for source, name in (
                ('/odm/etc/audio_config.xml', 'audio_config.xml'),
                ('/odm/etc/audio_route.xml', 'audio_route.xml'),
                ('/odm/etc/audio_params/sprd/audio_pga.xml', 'audio_pga.xml')):
            local = destination / 'raw' / name
            adb.call('pull', source, str(local), timeout=30)
            if sha(local) != adb.shell('sha256sum ' + source, root=True).split()[0]:
                raise ValueError('Own audio routing transfer mismatch')
            info = archive.gettarinfo(str(local), 'lib/firmware/changxing60-' + name)
            info.uid = info.gid = 0; info.mode = 0o644
            with local.open('rb') as stream:
                archive.addfile(info, stream)


def collect(adb, destination, busybox, backup):
    if not adb.serial or adb.root_status() != 'ready':
        raise ValueError('Select a rooted Android device')
    if (adb.shell('getprop ro.product.model').strip(), adb.shell('getprop ro.product.device').strip()) != ('ZTE 7552N', 'P720S20'):
        raise ValueError('Expected Changxing60 / P720S20')
    stock = json.loads((backup / 'manifest.json').read_text())
    slot = adb.shell('getprop ro.boot.slot_suffix').strip()
    if stock['profile'] != 'changxing60' or slot != '_' + stock['android_slot']:
        raise ValueError('Capture and current Android slots differ')
    destination = Path(destination).resolve()
    with ExitStack() as locks:
        locks.enter_context(DeviceLock(app_directory(), adb.serial))
        destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        spec = importlib.util.spec_from_file_location('cx60_firmware', TOP / 'openwrt/bundle/flash.py')
        flash = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(flash)
        flash.ADB, flash.SERIAL, flash.SU = adb.exe, adb.serial, adb.su
        flash.ANDROID_SLOT, flash.LINUX_SLOT = slot[1:], 'b' if slot == '_a' else 'a'
        flash.SCRIPTS = str(TOP)
        remote = '/data/local/tmp/cx60-vendor-' + secrets.token_hex(16)
        adb.shell('umask 077; mkdir ' + remote)
        flash.TMP = remote
        try:
            with tempfile.TemporaryDirectory() as directory:
                # The shared collector's default format uses AW87xxx and XPE
                # Bluetooth inputs, both observed on this device. No fake E5
                # install profile is passed and no installer mode is invoked.
                files = Path(directory)
                shutil.copyfile(busybox, files / 'busybox')
                shutil.copyfile(TOP / 'openwrt/bundle/collect-device-files.sh', files / 'collect-device-files.sh')
                flash.F = str(files)
                flash.android_tools()
                flash.pull_device_files(str(destination), remote + '/device-files.tar')
                expected = adb.shell('sha256sum ' + remote + '/device-files.tar', root=True, timeout=120).split()[0]
                size = int(adb.shell('wc -c < ' + remote + '/device-files.tar', root=True).strip())
                target = destination / 'device-files.tar'
                adb.call('pull', remote + '/device-files.tar', str(target), timeout=180)
                if target.stat().st_size != size or sha(target) != expected:
                    raise ValueError('Vendor archive transfer mismatch')
                enrich_audio(adb, destination)
                loader = destination / 'raw/aw87xxx_acf.bin'
                if not loader.is_file():
                    raise ValueError('Missing own amplifier firmware')
                if adb.shell('getprop ro.boot.slot_suffix').strip() != slot:
                    raise ValueError('Android slot changed during collection')
                atomic_json(destination / 'manifest.json', {
                    'profile': 'changxing60', 'android_slot': slot[1:],
                    'stock_build': adb.shell('getprop ro.build.fingerprint').strip(),
                    'archive_sha256': sha(target), 'archive_bytes': target.stat().st_size,
                    'source_archive_sha256': expected,
                    'raw': {p.name: sha(p) for p in (destination / 'raw').iterdir() if p.is_file()},
                    'nv_collected': False})
                return target
        finally:
            adb.shell('rm -rf ' + remote, root=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('out', 'busybox', 'backup'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    device = Adb(TOP, args.serial)
    device.exe = str(Path(args.adb).resolve())
    print(collect(device, args.out, args.busybox, args.backup))
