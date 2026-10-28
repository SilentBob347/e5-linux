"""NV partition discovery; opt-in UFS uses the same topology as initramfs.

Legacy boards retain their existing eMMC map. UFS never falls back to MMC or
chooses an arbitrary SCSI disk: resolve the unique internal userdata parent.
"""
import os
from pathlib import Path
import re
import subprocess


def identity(root=Path('/')):
    root = Path(root)
    marker = root / 'etc/e5/storage-kind'
    if not marker.exists() or marker.read_text().strip() == 'emmc':
        value = (root / 'sys/class/block/mmcblk0/device/cid').read_text().strip()
    elif marker.read_text().strip() == 'ufs':
        value = subprocess.check_output(
            ['sh', '-ec', '. "$1"; disk=$(e5_storage_disk); e5_storage_identity "$disk"',
             'storage-id', str(root / 'usr/lib/e5/storage.sh')], text=True, timeout=15,
            env=dict(os.environ, E5_STORAGE_SYS=str(root / 'sys/class/block'),
                     E5_UFS_ID_HELPER=str(root / 'usr/libexec/e5-ufs-id'))).strip()
    else:
        raise RuntimeError('Unsupported internal storage kind')
    if not re.fullmatch('[0-9a-fA-F]{32}', value):
        raise RuntimeError('Invalid internal storage identity')
    return value.lower()


def entries(root=Path('/')):
    root = Path(root)
    marker = root / 'etc/e5/storage-kind'
    kind = marker.read_text().strip() if marker.exists() else 'emmc'
    if kind == 'emmc':
        return sorted((root / 'sys/class/block').glob('mmcblk0p*/uevent'))
    if kind != 'ufs':
        raise RuntimeError('Unsupported internal storage kind')
    script = root / 'usr/lib/e5/storage.sh'
    disk = subprocess.check_output(
        ['sh', '-ec', '. "$1"; disk=$(e5_storage_disk); [ "$(e5_storage_kind "$disk")" = ufs ]; printf "%s\\n" "$disk"',
         'storage-map', str(script)],
        env=dict(os.environ, E5_STORAGE_SYS=str(root / 'sys/class/block')), text=True, timeout=15).strip()
    if not re.fullmatch(r'sd[a-z]+', disk):
        raise RuntimeError('Missing unique internal UFS user LUN')
    parent = (root / 'sys/class/block' / disk).resolve(strict=True)
    result = []
    for entry in (root / 'sys/class/block').glob(disk + '[0-9]*/uevent'):
        if entry.parent.resolve(strict=True).parent != parent:
            raise RuntimeError('UFS partition belongs to another disk')
        result.append(entry)
    return sorted(result)
