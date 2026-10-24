#!/usr/bin/python3
"""Shared NV maintenance: originals are opened read-only, never written here.

Calibration-only export requires a stock-confirmed item map. None has yet
been verified; advertising an entire runtime-NV writeback would be unsafe.
"""
import argparse
import array
import contextlib
try:
    import fcntl
except ImportError:  # Host-side Android recovery validates regular files only.
    fcntl = None
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

PAIRS = (('nr_fixnv1_a', 'nr_fixnv2_a'), ('nr_fixnv1_b', 'nr_fixnv2_b'),
         ('nr_runtimenv1', 'nr_runtimenv2'))

PROFILES = {'e5', 't551m', 'm8', 't512n', 'yuanhang41s', 'k1'}
NAMES = ('nr_fixnv1_a', 'nr_fixnv2_a', 'nr_fixnv1_b', 'nr_fixnv2_b',
         'nr_runtimenv1', 'nr_runtimenv2', 'nr_deltanv_a', 'nr_deltanv_b', 'calinv')
METHODS = {'status': {}, 'preview': {'direction': ''},
           'sync': {'direction': '', 'token': '', 'confirmation': '', 'conflict_ack': False}}


class NVError(RuntimeError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def flush_directory(path):
    if os.name == 'nt': return  # host staging; Windows has no O_DIRECTORY
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def storage_size(path):
    path = Path(path)
    if stat.S_ISBLK(path.stat().st_mode):
        with path.open('rb') as stream:
            return struct.unpack('Q', fcntl.ioctl(stream, 0x80081272, bytes(8)))[0]
    return path.stat().st_size


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    try:
        with temp.open('x', encoding='utf-8') as stream:
            os.chmod(temp, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
        flush_directory(path.parent)
    finally: temp.unlink(missing_ok=True)


def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default


def safe_directory(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise NVError('nv_unsafe_path')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


@contextlib.contextmanager
def maintenance_lock(root):
    """Same inode locks as full/diff upgrades; never remove a lock file."""
    with contextlib.ExitStack() as stack:
        for name in ('run/e5-part-update.lock', 'run/e5-upgrade/lock'):
            path = Path(root)/name
            if path.parent != Path(root)/'run': safe_directory(path.parent)
            else: path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise NVError('nv_unsafe_path')
            held = stack.enter_context(path.open('a'))
            os.chmod(path, 0o600)
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (Path(root)/'.e5-update/request.ready').exists() or (Path(root)/'.e5-update/request').exists():
            raise NVError('nv_busy')
        yield


def validate(path, name):
    """Same stock NV checksum variants as t551m-nv-prepare, including overflow.

    Delta/calinv formats are opaque: their hashes are tracked, not claimed
    checksum-valid or accepted as writable calibration item containers.
    """
    path = Path(path)
    if not name.startswith(('nr_fixnv', 'nr_runtimenv')):
        return 'opaque'
    with path.open('rb') as stream:
        header = stream.read(16)
        if len(header) != 16: raise NVError('nv_invalid_header')
        magic, size, expected, version = struct.unpack('<4I', header)
        if name.startswith('nr_runtimenv') and (magic, size, expected, version) == (0, 0, 0, 0):
            if any(any(block) for block in iter(lambda: stream.read(1024 * 1024), b'')):
                raise NVError('nv_invalid_runtime')
            return 'uninitialized'
        capacity = storage_size(path)
        if magic != 0x4e56 or size <= 0 or size % 2 or size > capacity - 512:
            raise NVError('nv_invalid_header')
        stream.seek(512); data = stream.read(size)
        if len(data) != size: raise NVError('nv_invalid_size')
        words = array.array('H', data)
        if sys.byteorder != 'little': words.byteswap()
        total = sum(words); checksums = []
        for number in (total, total & 0xffffffff):
            while number >> 16: number = (number & 0xffff) + (number >> 16)
            checksums.append(number ^ 0xffff)
        if expected not in checksums: raise NVError('nv_invalid_checksum')
    return 'valid'


def working(root):
    root = Path(root); store = root/'opt/e5/nv'
    if any(p.is_symlink() for p in (store, *store.parents)) or (store/'factory-sha256.json').is_symlink():
        raise NVError('nv_unsafe_path')
    origin = read_json(store/'factory-sha256.json', {})
    if (not isinstance(origin, dict) or set(origin) != set(NAMES) or
            any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in origin.values())):
        raise NVError('nv_origin_unavailable')
    values = {}
    for name in NAMES:
        path = store/name
        if path.is_symlink() or not path.is_file(): raise NVError('nv_work_unavailable')
        values[name] = {'sha256': digest(path), 'validation': validate(path, name), 'size': path.stat().st_size}
    return origin, values


@contextlib.contextmanager
def quiesced(root):
    """Reuse the deployed transaction-aware writer pause for a live snapshot."""
    stopped = []
    if Path(root) != Path('/'):
        yield
        return
    import runpy
    prepare = Path('/opt/e5/t551m-nv-prepare')
    helper = Path('/opt/e5/t551m-nv-stop')
    if not prepare.exists():
        yield
        return
    nv = runpy.run_path(str(prepare)); pids = nv['vendor_pids']()
    try:
        if pids:
            stop = runpy.run_path(str(helper))
            for pid in pids:
                identity = Path('/proc')/str(pid)/'stat'
                start = identity.read_text().rsplit(')', 1)[1].split()[19]
                # Preserve an already-stopped task's state.
                state = identity.read_text().rsplit(')', 1)[1].split()[0]
                if state in ('T', 't'): continue
                with contextlib.redirect_stdout(sys.stderr): stop['freeze_idle'](pid)
                stopped.append((pid, start))
        for path, loop in nv['attached_loops']().items():
            with loop.open('rb') as stream: os.fsync(stream.fileno())
            with path.open('rb') as stream: os.fsync(stream.fileno())
        yield
    finally:
        for pid, start in stopped:
            try:
                identity = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()[19]
                if identity == start: os.kill(pid, signal.SIGCONT)
            except (FileNotFoundError, ProcessLookupError): pass


def archive(root, output):
    with quiesced(root):
        return archive_quiet(root, output)


def factory_archive(root, output, devices=None):
    """A fresh-install snapshot from THIS unit's originals, never raw writes.

    No working-file checks are relaxed. Recovery uses a separately validated
    source and a new provenance manifest after explicit per-operation consent.
    devices is restricted to offline host fixtures/Android binary readback.
    """
    root = Path(root)
    manager = Manager(root, devices)
    profile, slot = manager.identity()
    sources = manager.map()
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='e5-nv-original-') as temporary:
        staged = Path(temporary); store = staged/'opt/e5/nv'; store.mkdir(parents=True, mode=0o700)
        (staged/'etc/e5').mkdir(parents=True)
        (staged/'etc/e5/device-profile').write_text(profile)
        for name in NAMES:
            source = sources[name]; validate(source, name); checksum = digest(source)
            with source.open('rb') as src, (store/name).open('xb') as dst:
                os.chmod(store/name, 0o660); shutil.copyfileobj(src, dst)
                dst.flush(); os.fsync(dst.fileno())
            if digest(store/name) != checksum or digest(source) != checksum:
                raise NVError('nv_snapshot_changed')
            hashes[name] = checksum
        if any(digest(sources[n]) != hashes[n] for n in NAMES): raise NVError('nv_snapshot_changed')
        for primary, redundant in PAIRS: shutil.copyfile(store/primary, store/redundant)
        atomic_json(store/'factory-sha256.json', hashes)
        atomic_json(staged/'etc/e5-nv/last-sync.json', {
            'direction': 'from-original', 'reason': 'confirmed-install-recovery',
            'time': int(time.time()), 'ok': True, 'reboot_required': False,
            'firmware_slot': slot})
        archive_quiet(staged, output)


def confirmed_factory_archive(root, output):
    """Interactive legacy shell path; a headless process never assumes yes."""
    with tempfile.TemporaryFile() as candidate:
        factory_archive(root, candidate)
        try:
            with open('/dev/tty', 'r') as reader, open('/dev/tty', 'w') as writer:
                writer.write('Working NV could not be preserved. Use this unit\'s original Android NV?\n'
                          '工作 NV 无法保留。改用本机原始 NV 将放弃 OpenWrt NV 修改，原机分区不变。\n'
                          'Type yes / 输入 yes: ')
                writer.flush()
                if reader.readline(32).strip() != 'yes': raise NVError('nv_confirmation_required')
        except OSError as error:
            raise NVError('nv_confirmation_required') from error
        candidate.seek(0); shutil.copyfileobj(candidate, output)


def archive_quiet(root, output):
    """Offline snapshot to stdout, before replacing a filesystem. No raw IO."""
    root = Path(root)
    profile = (root/'etc/e5/device-profile').read_text().strip()
    if profile not in PROFILES: raise NVError('nv_profile_unknown')
    store = root/'opt/e5/nv'
    if store.is_symlink(): raise NVError('nv_unsafe_path')
    if not store.exists(): return False
    origin, values = working(root)
    members = []
    for base in ('opt/e5/nv', 'etc/e5-nv'):
        directory = root/base
        if not directory.exists(): continue
        if directory.is_symlink(): raise NVError('nv_unsafe_path')
        for path in sorted(directory.rglob('*')):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise NVError('nv_unsafe_path')
            if path.is_file() and path.name != '.preserved.json': members.append(path)
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in members}
    metadata = json.dumps({'format': 1, 'profile': profile, 'files': hashes, 'working': values}).encode()
    with tarfile.open(fileobj=output, mode='w|') as tar:
        for path in members:
            tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            if digest(path) != hashes[path.relative_to(root).as_posix()]: raise NVError('nv_snapshot_changed')
        entry = tarfile.TarInfo('opt/e5/nv/.preserved.json'); entry.size = len(metadata); entry.mode = 0o600
        tar.addfile(entry, io.BytesIO(metadata))
    if any(digest(p) != hashes[p.relative_to(root).as_posix()] for p in members):
        raise NVError('nv_snapshot_changed')
    return True


def backup_work(root):
    root = Path(root); origin, values = working(root)
    state = root/'etc/e5-nv'; safe_directory(state)
    backups = state/'backups'; safe_directory(backups)
    target = backups/('update-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6))
    target.mkdir(mode=0o700)
    for name in (*NAMES, 'factory-sha256.json'):
        source = root/'opt/e5/nv'/name; destination = target/name
        with source.open('rb') as src, destination.open('xb') as dst:
            os.chmod(destination, 0o600); shutil.copyfileobj(src, dst); dst.flush(); os.fsync(dst.fileno())
        if digest(destination) != digest(source): raise NVError('nv_backup_failed')
    atomic_json(target/'record.json', {'kind': 'update-preservation', 'time': int(time.time()), 'files': values})
    return target


def recover_import(root):
    """Resolve only our journaled directory switch before normal NV startup."""
    root = Path(root); journal = root/'opt/e5/nv-import.json'
    if not journal.exists(): return
    if journal.is_symlink(): raise NVError('nv_unsafe_path')
    record = read_json(journal)
    relative = record.get('backup', '')
    if not re.fullmatch(r'etc/e5-nv/backups/[0-9]{8}-[0-9]{6}-[0-9a-f]{12}', relative):
        raise NVError('nv_import_journal_invalid')
    backup = root/relative
    if any(p.is_symlink() for p in (backup, *backup.parents)): raise NVError('nv_unsafe_path')
    store = root/'opt/e5/nv'
    if not store.exists():
        previous = backup/'previous-working'
        if previous.is_symlink() or not previous.is_dir(): raise NVError('nv_import_recovery_failed')
        saved = read_json(backup/'record.json')
        if not saved or any(digest(previous/n) != saved['work'][n] for n in NAMES):
            raise NVError('nv_import_recovery_failed')
        os.rename(previous, store)
    working(root)
    fd = os.open(store.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    journal.unlink()


def verify_preserved(root):
    root = Path(root); metadata = read_json(root/'opt/e5/nv/.preserved.json')
    if not metadata or metadata.get('format') != 1: raise NVError('nv_preservation_missing')
    if metadata['profile'] != (root/'etc/e5/device-profile').read_text().strip():
        raise NVError('nv_profile_mismatch')
    for name, checksum in metadata['files'].items():
        if (not name.startswith(('opt/e5/nv/', 'etc/e5-nv/')) or '..' in Path(name).parts
                or Path(name).is_absolute()): raise NVError('nv_unsafe_path')
        path = root/name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or digest(path) != checksum:
            raise NVError('nv_preservation_mismatch')
    working(root)
    return True


class Manager:
    def __init__(self, root=Path('/'), devices=None):
        self.root = Path(root); self.store = self.root/'opt/e5/nv'
        self.state = self.root/'etc/e5-nv'; self.ram = self.root/'run/e5-nv'
        self.devices = devices

    def map(self):
        if self.devices is not None:
            if self.root == Path('/'): raise NVError('nv_fixture_forbidden')
            return self.devices
        result = {}
        for entry in (self.root/'sys/class/block').glob('mmcblk0p*/uevent'):
            fields = dict(line.split('=', 1) for line in entry.read_text().splitlines() if '=' in line)
            name = fields.get('PARTNAME'); dev = fields.get('DEVNAME', '')
            if name not in NAMES: continue
            if name in result or not re.fullmatch(r'mmcblk0p[1-9][0-9]*', dev): raise NVError('nv_layout_unknown')
            path = self.root/'dev'/dev
            if path.is_symlink() or not stat.S_ISBLK(path.stat().st_mode): raise NVError('nv_layout_unknown')
            with path.open('rb') as stream:
                if struct.unpack('i', fcntl.ioctl(stream, 0x125e, bytes(4)))[0] != 1:
                    raise NVError('nv_original_not_protected')
            result[name] = path
        if set(result) != set(NAMES): raise NVError('nv_layout_unknown')
        return result

    def identity(self):
        profile = (self.root/'etc/e5/device-profile').read_text().strip()
        slot = (self.root/'etc/e5/modem-slot').read_text().strip()
        if profile not in PROFILES: raise NVError('nv_profile_unknown')
        if slot == 'current':
            slots = set(re.findall(r'(?:androidboot|sprdboot)\.slot_suffix=_([ab])(?:\s|$)',
                                  (self.root/'proc/cmdline').read_text()))
            if len(slots) != 1: raise NVError('nv_slot_unknown')
            slot = slots.pop()
        if slot not in ('a', 'b'): raise NVError('nv_slot_unknown')
        return profile, slot

    def inspect(self, local_state=None):
        profile, slot = self.identity()
        origin, local = local_state if local_state is not None else working(self.root)
        source = {}; opaque_changed = False
        for name, path in self.map().items():
            if storage_size(path) != local[name]['size']: raise NVError('nv_layout_unknown')
            valid = validate(path, name); checksum = digest(path)
            source[name] = {'sha256': checksum, 'validation': valid}
            if valid == 'opaque' and checksum != origin[name]: opaque_changed = True
        conflict = any(local[n]['sha256'] != origin[n] and source[n]['sha256'] != origin[n]
                       and local[n]['sha256'] != source[n]['sha256'] for n in NAMES)
        return {'profile': profile, 'firmware_slot': slot, 'origin': origin, 'local': local,
                'source': source, 'conflict': conflict, 'opaque_changed': opaque_changed}

    def boot_id(self):
        try: return (self.root/'proc/sys/kernel/random/boot_id').read_text().strip()
        except FileNotFoundError: return ''

    def status(self):
        job = read_json(self.ram/'job.json', {})
        if job.get('state') in ('queued', 'running'):
            return {'ok': True, 'busy': True, 'job': job, 'can_import': False, 'can_export': False}
        work_valid = False
        last = read_json(self.state/'last-sync.json', {})
        try:
            local = working(self.root); work_valid = True
            data = self.inspect(local)
            if last.get('boot_id') and last['boot_id'] != self.boot_id():
                last['reboot_required'] = False
            same = all(data['local'][n]['sha256'] == data['source'][n]['sha256'] for n in NAMES)
            return {'ok': True, 'initialized': True, 'validated': True,
                    'work_validated': True, 'original_validated': True, 'profile': data['profile'],
                    'firmware_slot': data['firmware_slot'], 'same': same, 'conflict': data['conflict'],
                    'can_import': not data['opaque_changed'], 'import_reason': 'nv_opaque_source_changed' if data['opaque_changed'] else '',
                    'can_export': False, 'export_reason': 'nv_calibration_rules_unverified',
                    'last_sync': last, 'job': job,
                    'backup_path': '/etc/e5-nv/backups'}
        except (OSError, ValueError, NVError) as error:
            return {'ok': True, 'initialized': self.store.exists(), 'validated': False,
                    'work_validated': work_valid, 'original_validated': False, 'last_sync': last,
                    'can_import': False, 'can_export': False, 'reason': str(error) if isinstance(error, NVError) else 'nv_state_unavailable',
                    'export_reason': 'nv_calibration_rules_unverified'}

    def preview(self, direction):
        if direction != 'from-original': raise NVError('nv_calibration_rules_unverified')
        data = self.inspect()
        if data['opaque_changed']: raise NVError('nv_opaque_source_changed')
        token = secrets.token_hex(24)
        atomic_json(self.ram/'preview.json', {'token': token, 'direction': direction, 'time': time.monotonic(), 'state': data})
        return {'ok': True, 'token': token, 'conflict': data['conflict'], 'reboot_required': True}

    def sync(self, data):
        if data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        if data.get('direction') != 'from-original': raise NVError('nv_calibration_rules_unverified')
        safe_directory(self.ram)
        with maintenance_lock(self.root), (self.ram/'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            saved = read_json(self.ram/'preview.json', {})
            if not secrets.compare_digest(str(saved.get('token', '')), str(data.get('token', ''))) or not saved.get('token'):
                raise NVError('nv_preview_expired')
            if time.monotonic() - saved['time'] > 300 or self.inspect() != saved['state']: raise NVError('nv_preview_expired')
            if saved['state']['conflict'] and data.get('conflict_ack') is not True: raise NVError('nv_conflict')
            required = 3 * sum(value['size'] for value in saved['state']['local'].values()) + (1 << 20)
            if shutil.disk_usage(self.store).free < required: raise NVError('nv_backup_space')
            backup = self.state/'backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(6))
            safe_directory(self.state)
            safe_directory(self.state/'backups')
            backup.mkdir(parents=True, mode=0o700)
            committed = False
            try:
                if self.store.stat().st_dev != backup.stat().st_dev: raise NVError('nv_layout_unknown')
                # A deferred charging-mode start must not reopen loops halfway
                # through the import. Shared nv-prepare honors this RAM marker.
                atomic_json(self.ram/'import-active', {'backup': str(backup), 'boot_id': self.boot_id()})
                # Existing service hooks quiesce the writer and flush/detach NV.
                # Do not issue SFUN or alter saved radio/replay preferences.
                subprocess.run(['/etc/init.d/e5-vendor', 'stop'], check=True, timeout=60)
                if self.root == Path('/'):
                    import runpy
                    if runpy.run_path('/opt/e5/t551m-nv-prepare')['vendor_pids']():
                        raise NVError('nv_writer_busy')
                if any((self.root/'sys/class/block').glob('loop*/loop/backing_file')):
                    for path in (self.root/'sys/class/block').glob('loop*/loop/backing_file'):
                        if path.read_text().strip().startswith(str(self.store)+'/'): raise NVError('nv_writer_busy')
                devices = self.map()
                for name in NAMES:
                    for label, path in (('work', self.store/name), ('source', devices[name])):
                        target = backup/label/name; target.parent.mkdir(exist_ok=True, mode=0o700)
                        with path.open('rb') as src, target.open('xb') as dst:
                            os.chmod(target, 0o600)
                            shutil.copyfileobj(src, dst); dst.flush(); os.fsync(dst.fileno())
                        if digest(target) != digest(path): raise NVError('nv_backup_failed')
                        if label == 'source' and digest(target) != saved['state']['source'][name]['sha256']:
                            raise NVError('nv_preview_expired')
                atomic_json(backup/'factory-sha256.json', saved['state']['origin'])
                flush_directory(backup/'work'); flush_directory(backup/'source')
                atomic_json(backup/'record.json', {'complete': True, 'source': saved['state']['source'],
                            'work': {n: digest(backup/'work'/n) for n in NAMES}})
                # Stage a COMPLETE replacement, even if Android's hashes have
                # not changed. --refresh only updates changed source hashes and
                # would otherwise silently retain OpenWrt calibration changes.
                candidate = backup/'import'
                candidate.mkdir(mode=0o700)
                for name in NAMES:
                    shutil.copyfile(backup/'source'/name, candidate/name)
                    os.chmod(candidate/name, 0o660)
                    if self.root == Path('/'): os.chown(candidate/name, 1000, 1000)
                    validate(candidate/name, name)
                # Reuse the verified primary-first redundant-copy rule. Only
                # isolated candidate files are reconciled, never raw partitions.
                for primary, redundant in PAIRS:
                    shutil.copyfile(candidate/primary, candidate/redundant)
                    if self.root == Path('/'): os.chown(candidate/redundant, 1000, 1000)
                atomic_json(candidate/'factory-sha256.json',
                            {n: saved['state']['source'][n]['sha256'] for n in NAMES})
                for name in NAMES:
                    expected = saved['state']['source'][next((p for p, r in PAIRS if r == name), name)]['sha256']
                    if digest(candidate/name) != expected: raise NVError('nv_preservation_mismatch')
                # Each staged file has a verified checksum and flushed bytes.
                for name in (*NAMES, 'factory-sha256.json'):
                    with (candidate/name).open('rb') as stream: os.fsync(stream.fileno())
                # Both locations are on the root filesystem. Keep the old
                # directory intact for immediate rollback if commit fails.
                old = backup/'previous-working'
                journal = self.root/'opt/e5/nv-import.json'
                atomic_json(journal, {'backup': backup.relative_to(self.root).as_posix()})
                os.rename(self.store, old)
                try:
                    flush_directory(backup); flush_directory(self.store.parent)
                    os.rename(candidate, self.store)
                    fd = os.open(self.store.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
                    committed = True
                    journal.unlink()
                except Exception:
                    if not self.store.exists():
                        os.rename(old, self.store)
                        flush_directory(self.store.parent); flush_directory(backup)
                    raise
                self.ram.joinpath('preview.json').unlink(missing_ok=True)
                outcome = {'direction': 'from-original', 'time': int(time.time()),
                           'backup': str(backup).removeprefix(str(self.root)) if self.root != Path('/') else str(backup),
                           'reboot_required': True, 'ok': True, 'boot_id': self.boot_id()}
                atomic_json(self.state/'last-sync.json', outcome)
                return outcome
            except Exception as error:
                # No originals were opened for writing. Keep diagnostics and
                # both complete/partial backups; do not resume on uncertain NV.
                atomic_json(self.state/'last-sync.json', {'direction': 'from-original', 'time': int(time.time()),
                            'backup': str(backup), 'ok': False, 'error': 'nv_import_failed',
                            'cause': str(error), 'committed': committed, 'reboot_required': True,
                            'boot_id': self.boot_id()})
                raise NVError('nv_import_failed')

    def start(self, data):
        if data.get('confirmation') != 'yes': raise NVError('nv_confirmation_required')
        if data.get('direction') != 'from-original': raise NVError('nv_calibration_rules_unverified')
        safe_directory(self.ram)
        with (self.ram/'launch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if read_json(self.ram/'job.json', {}).get('state') in ('queued', 'running'): raise NVError('nv_busy')
            token = secrets.token_hex(12); request = self.ram/('request-'+token+'.json')
            atomic_json(request, data)
            atomic_json(self.ram/'job.json', {'id': token, 'state': 'queued'})
            try:
                with (self.ram/'worker.log').open('ab') as log:
                    os.chmod(self.ram/'worker.log', 0o600)
                    subprocess.Popen([sys.executable, __file__, 'worker', str(request)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            except Exception:
                atomic_json(self.ram/'job.json', {'id': token, 'state': 'failed', 'error': 'nv_operation_failed'})
                request.unlink(missing_ok=True)
                raise
        return {'ok': True, 'job': {'id': token, 'state': 'queued'}}


def dispatch(method, data):
    manager = Manager()
    if method == 'status': return manager.status()
    if method == 'preview': return manager.preview(data.get('direction'))
    if method == 'sync': return manager.start(data)
    raise NVError('nv_invalid_method')


def run_worker(request, manager):
    request = Path(request)
    if request.parent != manager.ram or not re.fullmatch(r'request-[0-9a-f]{24}\.json', request.name):
        raise NVError('nv_invalid_request')
    token = request.stem.removeprefix('request-')
    atomic_json(manager.ram/'job.json', {'id': token, 'state': 'running'})
    try:
        result = manager.sync(read_json(request, {}))
        atomic_json(manager.ram/'job.json', {'id': token, 'state': 'complete', 'result': result})
    except Exception as error:
        code = 'nv_busy' if isinstance(error, BlockingIOError) else str(error) if isinstance(error, NVError) else 'nv_operation_failed'
        atomic_json(manager.ram/'job.json', {'id': token, 'state': 'failed', 'error': code})
    finally: request.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('archive', 'factory-archive', 'factory-confirmed', 'verify', 'update-backup', 'worker'))
    parser.add_argument('request', nargs='?')
    parser.add_argument('--root', default='/')
    parser.add_argument('--lock', action='store_true')
    args = parser.parse_args()
    if args.operation in ('archive', 'factory-archive', 'factory-confirmed'):
        with maintenance_lock(Path(args.root)) if args.lock else contextlib.nullcontext():
            if args.operation == 'factory-confirmed': confirmed_factory_archive(Path(args.root), sys.stdout.buffer)
            elif args.operation == 'factory-archive': factory_archive(Path(args.root), sys.stdout.buffer)
            elif not archive(Path(args.root), sys.stdout.buffer): raise SystemExit(3)
    elif args.operation == 'verify': verify_preserved(Path(args.root))
    elif args.operation == 'update-backup': backup_work(Path(args.root))
    else:
        if args.root != '/' or not args.request: raise NVError('nv_invalid_request')
        run_worker(Path(args.request), Manager())
