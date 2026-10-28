#!/usr/bin/env python3
"""Read-only stock evidence for ZTE 7552N/P720S20; never reads raw NV.

Binary reads are accepted only after comparison with the source SHA256.
No property changes, block writes, partition mounts, reboots or USB changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--references-only', action='store_true', help='Collect selected stock drivers, firmware and RIL; reuse initial capture')
    args = parser.parse_args()
    adb = [args.adb, '-s', args.serial, 'exec-out', 'su', '-c']

    def read(command, timeout=180):
        # This device's su uses a PTY; suppress its newline conversion. The
        # source hash below rejects a damaged binary rather than repairing it.
        return subprocess.check_output(adb + ['stty -onlcr 2>/dev/null; ' + command], timeout=timeout)

    def text(command):
        return read(command).decode('utf-8', 'replace').replace('\r\n', '\n').strip()

    if (text('getprop ro.product.model'), text('getprop ro.product.device')) != ('ZTE 7552N', 'P720S20'):
        raise ValueError('Expected Changxing 60 / ZTE 7552N / P720S20')
    if 'uid=0(root)' not in text('id'):
        raise ValueError('Root access required')
    slot = text('getprop ro.boot.slot_suffix')
    if slot not in ('_a', '_b'):
        raise ValueError('Unknown current Android slot')
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'format': 1, 'profile': 'changxing60', 'model': 'ZTE 7552N', 'board': 'P720S20',
        'android_slot': slot[1:], 'device_modified': False, 'files': {}}
    if manifest.get('android_slot') != slot[1:]:
        raise ValueError('Existing capture belongs to another running slot; keep it and select a different output')

    def record(name, data, source, checksum=None):
        checksum = checksum or hashlib.sha256(data).hexdigest()
        destination = args.out / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        manifest['files'][name] = {'bytes': len(data), 'sha256': checksum, 'source': source}
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        print(name, len(data), flush=True)

    def file(name, source, limit=None):
        quoted = shlex.quote(source)
        exists = text('test -r ' + quoted + ' && echo yes || true')
        if exists != 'yes':
            print('not available:', source, flush=True)
            return
        command = 'cat ' + quoted if limit is None else f'dd if={quoted} bs=4096 count={limit} 2>/dev/null'
        checksum = text('(' + command + ') | sha256sum').split()[0]
        old = manifest['files'].get(name)
        destination = args.out / name
        if old and old['sha256'] == checksum and destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == checksum:
            print('verified existing:', name, flush=True)
            return
        data = read(command)
        if hashlib.sha256(data).hexdigest() != checksum:
            raise ValueError('Binary transfer checksum mismatch: ' + source)
        record(name, data, source, checksum)

    if args.references_only:
        candidates = text('find /vendor/lib/modules /vendor_dlkm/lib/modules /vendor/firmware /odm/firmware -maxdepth 2 -type f 2>/dev/null; true').splitlines()
        names = {'ufs_sprd_qogirn6pro.ko', 'zte_tpd.ko', 'sqc_bq2560x.ko',
                 'sprd_charger_manager.ko', 'sc27xx_fuel_gauge.ko', 'charger_policy_service.ko',
                 'snd-soc-aw87xxx.ko', 'sprd_drm.ko', 'sprd_cpufreq_v2.ko',
                 'aw87xxx_acf.bin'}
        for source in candidates:
            basename = Path(source).name
            if basename in names or basename.startswith('axs_firmware_'):
                file('reference/' + source.lstrip('/'), source)
        for source in ('/vendor/lib64/libimpl-ril.so', '/vendor/bin/modem_control',
                       '/vendor/bin/cp_diskserver', '/vendor/bin/refnotify',
                       '/odm/etc/audio_route.xml', '/odm/etc/audio_route_ab.xml', '/odm/etc/audio_pga.xml',
                       '/odm/etc/audio_params/sprd/audio_pga.xml', '/odm/etc/audio_params/sprd/codec.xml'):
            file('reference/' + source.lstrip('/'), source)
        return

    commands = {
        'properties.txt': 'getprop', 'uname.txt': 'uname -a', 'cmdline.txt': 'cat /proc/cmdline',
        'bootconfig.txt': 'cat /proc/bootconfig 2>/dev/null; true',
        'mounts.txt': 'cat /proc/mounts; df -h /data', 'dmesg.txt': 'dmesg',
        'partitions.txt': 'ls -l /dev/block/by-name; cat /proc/partitions',
        'storage.txt': '''for d in /sys/class/block/sd*; do
 echo "$d"; readlink -f "$d"; cat "$d/start" "$d/size" "$d/partition" "$d/queue/logical_block_size" "$d/queue/physical_block_size" 2>/dev/null
done
for d in /sys/bus/platform/devices/*.ufs; do
 echo "$d"; readlink "$d/driver"; cat "$d/of_node/compatible"; echo
 for f in clkgate_enable clkgate_delay_ms clkscale_enable rpm_lvl spm_lvl power/control power/runtime_status string_descriptors/manufacturer_name string_descriptors/product_name string_descriptors/serial_number; do echo "$f"; cat "$d/$f" 2>/dev/null; done
done; true''',
        'inputs.txt': 'cat /proc/bus/input/devices', 'modules.txt': 'cat /proc/modules',
        'i2c.txt': 'for d in /sys/bus/i2c/devices/*; do [ -e "$d/name" ] || continue; echo "$d"; cat "$d/name"; readlink "$d/driver"; done; true',
        'power.txt': 'for d in /sys/class/power_supply/*; do echo "$d"; cat "$d/uevent" 2>/dev/null; done; true',
        'display.txt': 'wm size; wm density; for d in /sys/class/backlight/*; do echo "$d"; cat "$d/brightness" "$d/max_brightness"; done; dumpsys SurfaceFlinger --display-id',
        'crypto.txt': 'getprop ro.crypto.state; getprop ro.crypto.type; cat /vendor/etc/fstab* /odm/etc/fstab* 2>/dev/null; true',
        'sound.txt': 'cat /proc/asound/cards; cat /proc/asound/pcm; ls /odm/etc/audio* /vendor/etc/audio* 2>/dev/null; true',
        'cpu.txt': 'for d in /sys/devices/system/cpu/cpufreq/policy*; do echo "$d"; cat "$d/scaling_driver" "$d/scaling_available_frequencies" "$d/scaling_governor"; done; true',
        'runtime-files.txt': 'find /vendor/lib/modules /vendor_dlkm/lib/modules /odm/firmware /vendor/firmware -maxdepth 2 -type f 2>/dev/null; ls /vendor/bin/*modem* /vendor/bin/*diskserver* /vendor/bin/refnotify /vendor/lib64/*ril* /vendor/lib/*ril* 2>/dev/null; true',
    }
    for name, command in commands.items():
        record(name, read(command).replace(b'\r\n', b'\n'), command)
    file('live.dtb', '/sys/firmware/fdt')
    file('config.gz', '/proc/config.gz')
    for partition in ('boot_a', 'boot_b', 'vendor_boot_a', 'vendor_boot_b', 'init_boot_a', 'init_boot_b',
                      'dtb_a', 'dtb_b', 'dtbo_a', 'dtbo_b', 'uboot_a', 'uboot_b', 'sml_a', 'sml_b',
                      'teecfg_a', 'teecfg_b', 'trustos_a', 'trustos_b', 'vbmeta_a', 'vbmeta_b'):
        file(partition + '.img', '/dev/block/by-name/' + partition)
    file('misc-head.bin', '/dev/block/by-name/misc', limit=1)


if __name__ == '__main__':
    main()
