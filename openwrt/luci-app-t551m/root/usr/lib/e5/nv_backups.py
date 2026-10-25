"""Manual consistent snapshots and authenticated download preparation.

One RAM export cache; no uncompressed staging and no original-partition writes.
"""
import errno
import hashlib
import io
import json
import os
import re
import tarfile
import time


def manual_backup(manager):
    import nv_persistence as nv
    with nv.maintenance_lock(manager.root):
        if (manager.state/'writeback.json').exists() or (manager.root/'opt/e5/nv-import.json').exists():
            raise nv.NVError('nv_recovery_pending')
        profile, slot = manager.identity(); sources = manager.map()
        backup=manager.state/'backups'/('manual-'+time.strftime('%Y%m%d-%H%M%S')+'-'+nv.secrets.token_hex(6))
        nv.safe_directory(backup); manager.phase('backup')
        nv.atomic_json(backup/'record.json',{'kind':'manual','complete':False,'storage':'gzip',
                       'time':int(time.time()),'profile':profile,'firmware_slot':slot})
        # Reuse the existing idle writer pause/flush, never vendor stop or AT.
        with nv.quiesced(manager.root):
            origin, values=nv.working(manager.root); hashes={}
            for name in nv.NAMES: hashes[name]=nv.save_snapshot(manager.store/name,backup/'work'/name)
            nv.atomic_json(backup/'factory-sha256.json',origin)
        original={}
        for name in nv.NAMES:
            if nv.storage_size(sources[name])!=values[name]['size']:raise nv.NVError('nv_layout_unknown')
            valid=nv.validate(sources[name],name)
            original[name]={'sha256':nv.save_snapshot(sources[name],backup/'source'/name),'validation':valid}
        nv.atomic_json(backup/'record.json',{'kind':'manual','complete':True,'storage':'gzip',
            'time':int(time.time()),'profile':profile,'firmware_slot':slot,
            'raw_bytes':2*sum(v['size'] for v in values.values()),'source':original,'work':hashes})
        return {'ok':True,'manual_backup':True,'id':backup.name,'backup':'/'+backup.relative_to(manager.root).as_posix()}


def prepare_download(manager,data):
    import nv_persistence as nv
    ident=data.get('id','')
    if not isinstance(ident,str) or not re.fullmatch(r'(?:(?:update|manual)-)?[0-9]{8}-[0-9]{6}-[0-9a-f]{12}',ident):
        raise nv.NVError('nv_invalid_request')
    with nv.maintenance_lock(manager.root):
        row=next((r for r in manager.backups()['entries'] if r['id']==ident),None)
        if row is None:raise nv.NVError('nv_backup_missing')
        if row['protected']:raise nv.NVError('nv_recovery_pending')
        backup=manager.state/'backups'/ident
        if any(p.is_symlink() for p in (backup,*backup.parents)):raise nv.NVError('nv_unsafe_path')
        files=sorted(backup.rglob('*'))
        if any(p.is_symlink() or not(p.is_file() or p.is_dir()) for p in files):raise nv.NVError('nv_unsafe_path')
        files=[p for p in files if p.is_file()]
        output=manager.root/'tmp/e5-nv-download';nv.safe_directory(output)
        for old in output.iterdir():
            if re.fullmatch(r'\.export-[0-9a-f]{24}\.part',old.name) and old.is_file() and not old.is_symlink():old.unlink()
        token=nv.secrets.token_hex(12);temporary=output/('.export-'+token+'.part');final=output/('export-'+token+'.tar.gz')
        manager.phase('exporting');profile=manager.identity()[0];prefix=profile+'-nv-backup-'+ident
        manifest={'format':1,'backup':ident,'profile':profile,'files':{}}
        try:
            with temporary.open('xb') as target:
                os.chmod(temporary,0o600)
                with tarfile.open(fileobj=target,mode='w:gz',compresslevel=3) as archive:
                    for path in files:
                        relative=path.relative_to(backup).as_posix();checksum=nv.digest(path)
                        manifest['files'][relative]={'sha256':checksum,'bytes':path.stat().st_size}
                        archive.add(path,arcname=prefix+'/files/'+relative,recursive=False)
                        if nv.digest(path)!=checksum:raise nv.NVError('nv_snapshot_changed')
                    entries=[('download-manifest.json',json.dumps(manifest,sort_keys=True).encode()),
                        ('README.txt',b'Full NV backup; stored snapshots and records are preserved.\n'
                         b'Files ending in .gz are lossless full-file snapshots. Decompress them before using raw NV tools.\n'
                         b'download-manifest.json hashes the stored files, not their decompressed contents.\n')]
                    for name,raw in entries:
                        info=tarfile.TarInfo(prefix+'/'+name);info.size=len(raw);info.mode=0o600;archive.addfile(info,io.BytesIO(raw))
                target.flush();os.fsync(target.fileno())
            verified=set()
            with tarfile.open(temporary,'r:gz') as archive:
                for member in archive:
                    if not member.name.startswith(prefix+'/files/'):continue
                    relative=member.name[len(prefix+'/files/'):]
                    if relative not in manifest['files']:continue
                    if relative in verified or not member.isfile():raise nv.NVError('nv_backup_failed')
                    stream=archive.extractfile(member);h=hashlib.sha256();count=0
                    for block in iter(lambda:stream.read(1<<20),b''):h.update(block);count+=len(block)
                    expected=manifest['files'][relative]
                    if count!=expected['bytes'] or h.hexdigest()!=expected['sha256']:raise nv.NVError('nv_backup_failed')
                    verified.add(relative)
            if verified!=set(manifest['files']):raise nv.NVError('nv_backup_failed')
            os.replace(temporary,final);nv.flush_directory(output)
            # Open CGI transfers retain their fd. Old cache names can never
            # resolve to a DIFFERENT backup after a concurrent new export.
            for old in output.iterdir():
                if old!=final and re.fullmatch(r'export-[0-9a-f]{24}\.tar\.gz',old.name) and old.is_file() and not old.is_symlink():old.unlink()
            return {'ok':True,'download':{'path':'/'+final.relative_to(manager.root).as_posix(),
                    'filename':prefix+'.tar.gz','bytes':final.stat().st_size}}
        except OSError as error:
            if error.errno==errno.ENOSPC:raise nv.NVError('nv_backup_space') from error
            raise
        finally:temporary.unlink(missing_ok=True)
