"""Explicit full NV writeback, backup-first with verified recovery.

Each A/B working file replaces its matching physical partition byte for byte,
including identities and framing. Opaque images require verified provenance or
a known compatible format; merely computing a new hash is not validation.
"""
import contextlib
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import stat
import struct
import time

from nv_format import FixedNV, FormatError

FIXED = ('nr_fixnv1_a', 'nr_fixnv2_a', 'nr_fixnv1_b', 'nr_fixnv2_b')
CONTRACT = 'full-nv-v3-verified'


def read_imeis(manager):
    import nv_persistence as nv
    _, slot = manager.identity(); primary = 'nr_fixnv1_'+slot
    result = {}
    for name in ('working', 'original'):
        try:
            path = manager.store/primary if name == 'working' else manager.map()[primary]
            if not path.is_symlink(): result[name] = FixedNV.read(path).imeis()
        except (OSError, ValueError, nv.NVError): pass
    return result


def overview(manager, state):
    from nv_opaque import eligibility
    slot = state['firmware_slot']; primary = 'nr_fixnv1_'+slot
    details = {'comparison': None, 'imei': read_imeis(manager),
               'fixed_equal': all(state['local'][n]['sha256'] == state['source'][n]['sha256'] for n in FIXED),
               **eligibility(manager, state)}
    try:
        work = FixedNV.read(manager.store/primary); source = FixedNV.read(manager.map()[primary])
        details.update(comparison=work.difference(source), layout='VN101-INDX2')
    except (OSError, ValueError):
        # A full, validated container copy does not depend on a TLV item map.
        details['layout'] = 'VN-container'
    return details


def preview_writeback(manager, state):
    import nv_persistence as nv
    devices = manager.map(); device_identity(manager)
    details = overview(manager, state)
    for name in details['writeback_scope']:
        if nv.storage_size(devices[name]) != (manager.store/name).stat().st_size:
            raise FormatError('nv_layout_unknown')
        nv.validate(devices[name], name); nv.validate(manager.store/name, name)
    return {**details, 'writeback_contract': CONTRACT, 'writeback_files':
            sum(state['local'][n]['sha256'] != state['source'][n]['sha256'] for n in details['writeback_scope'])}


def device_identity(manager):
    try:
        kind = manager.root/'etc/e5/storage-kind'
        if kind.exists() and kind.read_text().strip() == 'ufs':
            import runpy
            cid = runpy.run_path(str(manager.root/'usr/lib/e5/block_storage.py'))['identity'](manager.root)
        else:
            cid = (manager.root/'sys/class/block/mmcblk0/device/cid').read_text().strip()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise FormatError('nv_device_unknown') from error
    if not re.fullmatch('[0-9a-fA-F]{32}', cid): raise FormatError('nv_device_unknown')
    return {'profile': manager.identity()[0], 'slot': manager.identity()[1], 'cid': cid.lower()}


class PairWriter:
    def __init__(self, allow_files=False): self.allow_files = allow_files

    @contextlib.contextmanager
    def writable(self, path):
        block = stat.S_ISBLK(path.stat().st_mode)
        if not block and not self.allow_files: raise FormatError('nv_layout_unknown')
        with path.open('rb') as guard:
            if block:
                before = struct.unpack('i', fcntl.ioctl(guard, 0x125e, bytes(4)))[0]
                if before != 1: raise FormatError('nv_original_not_protected')
                fcntl.ioctl(guard, 0x125d, struct.pack('i', 0))
            try: yield
            finally:
                if block:
                    fcntl.ioctl(guard, 0x125d, struct.pack('i', before))
                    if struct.unpack('i', fcntl.ioctl(guard, 0x125e, bytes(4)))[0] != before:
                        raise FormatError('nv_protection_restore_failed')

    def write(self, source, target, checksum):
        import nv_persistence as nv
        if source.name not in nv.NAMES: raise FormatError('nv_invalid_request')
        nv.verify_snapshot(source, checksum, nv.storage_size(target))
        with self.writable(target):
            fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                with nv.snapshot_reader(source) as stream:
                    for block in iter(lambda: stream.read(1 << 20), b''):
                        view = memoryview(block)
                        while view:
                            count = os.write(fd, view)
                            if count <= 0: raise OSError('short NV write')
                            view = view[count:]
                os.fsync(fd)
            finally: os.close(fd)
        if nv.digest(target) != checksum: raise FormatError('nv_original_readback_failed')
        nv.validate(target, source.name)


def write_order(names):
    order = [name for slot in ('a', 'b') for name in ('nr_fixnv2_'+slot, 'nr_fixnv1_'+slot)]
    order += ['nr_runtimenv2', 'nr_runtimenv1', 'nr_deltanv_a', 'nr_deltanv_b', 'calinv']
    return [name for name in order if name in names]


def verified_journal(manager, record, need_after=True):
    import nv_persistence as nv
    version = record.get('format'); relative = record.get('backup', '')
    if (version not in (1, 2, 3) or record.get('identity') != device_identity(manager)
            or not re.fullmatch(r'etc/e5-nv/backups/[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', relative)):
        raise FormatError('nv_writeback_recovery_mismatch')
    # Existing in-flight v1 item-merge transactions retain their own immutable
    # candidates. New transactions exclusively use full A/B working snapshots.
    slot = manager.identity()[1]
    if version == 3:
        names = record.get('names', [])
        core = set(FIXED) | {'nr_runtimenv1', 'nr_runtimenv2'}
        if (not isinstance(names, list) or any(not isinstance(n,str) for n in names)
                or not core.issubset(names) or names != [n for n in nv.NAMES if n in names]):
            raise FormatError('nv_writeback_recovery_mismatch')
    else: names = list(FIXED) if version == 2 else ['nr_fixnv1_'+slot, 'nr_fixnv2_'+slot]
    if record.get('names') != names or any(set(record.get(k, {})) != set(names) for k in ('before', 'after')):
        raise FormatError('nv_writeback_recovery_mismatch')
    backup = manager.root/relative
    if any(p.is_symlink() for p in (backup, *backup.parents)): raise FormatError('nv_unsafe_path')
    manifest = backup/'factory-sha256.json'
    if manifest.is_symlink() or nv.digest(manifest) != record.get('origin_sha256'):
        raise FormatError('nv_writeback_recovery_mismatch')
    origin = nv.read_json(manifest)
    if (not isinstance(origin, dict) or set(origin) != set(nv.NAMES) or
            any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in origin.values())):
        raise FormatError('nv_writeback_recovery_mismatch')
    devices = manager.map()
    for name in names:
        images = [('source', record['before'][name])]
        if need_after: images.append(('work' if version >= 2 else 'candidate', record['after'][name]))
        for kind, expected in images:
            nv.verify_snapshot(backup/kind/name, expected, nv.storage_size(devices[name]))
    return backup, devices, names


def rollback(manager, record, writer=None):
    import nv_persistence as nv
    backup, devices, names = verified_journal(manager, record, need_after=False)
    writer = writer or PairWriter(manager.root != Path('/'))
    for name in write_order(names):
        if nv.digest(devices[name]) != record['before'][name]:
            writer.write(backup/'source'/name, devices[name], record['before'][name])
    if any(nv.digest(devices[n]) != record['before'][n] for n in names):
        raise FormatError('nv_writeback_recovery_failed')
    nv.atomic_json(manager.store/'factory-sha256.json', nv.read_json(backup/'factory-sha256.json'))


def recover_writeback(manager):
    import nv_persistence as nv
    journal = manager.state/'writeback.json'
    if not journal.exists(): return
    record = nv.read_json(journal); backup, devices, names = verified_journal(manager, record, need_after=False)
    finished = all(nv.digest(devices[n]) == record['after'][n] for n in names)
    if finished:
        try: verified_journal(manager, record)
        except (OSError, nv.NVError): finished = False
    if not finished: rollback(manager, record)
    if finished:
        origin = nv.read_json(backup/'factory-sha256.json'); origin.update(record['after'])
        nv.atomic_json(manager.store/'factory-sha256.json', origin)
    nv.atomic_json(manager.state/'last-sync.json', {'direction': 'to-original', 'time': int(time.time()),
        'backup': '/'+backup.relative_to(manager.root).as_posix(), 'ok': finished, 'recovered': True,
        'error': '' if finished else 'nv_interrupted_recovered', 'reboot_required': False, 'boot_id': manager.boot_id()})
    journal.unlink(); nv.flush_directory(journal.parent)


def writeback(manager, saved, progress=lambda phase: None, writer=None, backup=None):
    import nv_persistence as nv
    # A confirmation generated for the old four-file policy must never silently
    # authorize the expanded runtime/calibration scope after a hot update.
    if saved.get('writeback_contract') != CONTRACT: raise FormatError('nv_preview_expired')
    devices = manager.map(); plan = preview_writeback(manager, saved['state']); names = plan['writeback_scope']
    if saved.get('writeback_scope') != names: raise FormatError('nv_preview_expired')
    required = 2*sum(nv.storage_size(devices[n]) for n in names)+(1 << 20)
    if shutil.disk_usage(manager.store).free < required: raise FormatError('nv_backup_space')
    backup = backup or manager.state/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+nv.secrets.token_hex(6))
    nv.safe_directory(backup); writer = writer or PairWriter(manager.root != Path('/')); record = None
    try:
        progress('backup'); before = {}; after = {}
        for name in names:
            nv.validate(devices[name], name); nv.validate(manager.store/name, name)
            before[name] = nv.save_snapshot(devices[name], backup/'source'/name)
            after[name] = nv.save_snapshot(manager.store/name, backup/'work'/name)
            if before[name] != saved['state']['source'][name]['sha256'] or after[name] != saved['state']['local'][name]['sha256']:
                raise FormatError('nv_preview_expired')
        nv.atomic_json(backup/'factory-sha256.json', saved['state']['origin'])
        changed = [n for n in names if before[n] != after[n]]
        record = {'format': 3, 'identity': device_identity(manager), 'backup': backup.relative_to(manager.root).as_posix(),
                  'names': names, 'before': before, 'after': after, 'origin_sha256': nv.digest(backup/'factory-sha256.json'),
                  'phase': 'prepared', 'boot_id': manager.boot_id()}
        nv.atomic_json(backup/'record.json', {'kind': 'nv-writeback', 'complete': True, 'storage': 'gzip',
            'raw_bytes': 2*sum(nv.storage_size(devices[n]) for n in names),
            'identity': record['identity'], 'source': before, 'work': after})
        if any(nv.digest(devices[n]) != before[n] for n in names): raise FormatError('nv_preview_expired')
        if changed:
            nv.atomic_json(manager.state/'writeback.json', record)
            for name in write_order(names):
                if name not in changed: continue
                progress('write-backup' if name.startswith('nr_fixnv2') or name == 'nr_runtimenv2'
                         else 'write-primary' if name.startswith(('nr_fixnv1','nr_runtimenv1')) else 'write-calibration')
                writer.write(backup/'work'/name, devices[name], after[name])
                record['phase'] = name+'-verified'; nv.atomic_json(manager.state/'writeback.json', record)
            if any(nv.digest(devices[n]) != after[n] for n in names): raise FormatError('nv_original_readback_failed')
            origin = dict(saved['state']['origin']); origin.update(after)
            nv.atomic_json(manager.store/'factory-sha256.json', origin)
        outcome = {'direction': 'to-original', 'time': int(time.time()), 'ok': True,
            'nv_files': len(changed), 'unchanged': not changed, 'scope': 'all-nv-validated',
            'skipped_files': plan['writeback_blocked'],
            'backup': '/'+backup.relative_to(manager.root).as_posix(), 'reboot_required': True, 'boot_id': manager.boot_id()}
        nv.atomic_json(manager.state/'last-sync.json', outcome)
        if (manager.state/'writeback.json').exists():
            (manager.state/'writeback.json').unlink(); nv.flush_directory(manager.state)
        return outcome
    except Exception as error:
        if record is not None and (manager.state/'writeback.json').exists():
            try:
                rollback(manager, record, PairWriter(manager.root != Path('/')))
                (manager.state/'writeback.json').unlink(); nv.flush_directory(manager.state)
            except Exception: raise FormatError('nv_writeback_recovery_required') from error
        raise
