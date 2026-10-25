#!/usr/bin/env python3
"""Manual snapshots/downloads using synthetic files only; no physical NV IO."""
import contextlib
import errno
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('nv_fixtures',Path(__file__).with_name('nv-persistence.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
nv=fixtures.nv
import nv_backups as backups


class BackupTests(unittest.TestCase):
    setUp=fixtures.NVTests.setUp

    def test_manual_full_snapshots_are_verified_and_never_modify_nv(self):
        before={p:p.read_bytes() for p in [*self.devices.values(),*self.store.iterdir()]}
        with patch.object(nv.subprocess,'run') as run:
            result=backups.manual_backup(self.manager)
            run.assert_not_called()
        row=self.manager.backups()['entries'][0]
        self.assertEqual(row['id'],result['id']);self.assertTrue(row['complete'])
        self.assertEqual(row['kind'],'manual');self.assertTrue(row['compressed'])
        folder=self.manager.state/'backups'/result['id']
        for name in nv.NAMES:
            for side,path in [('source',self.devices[name]),('work',self.store/name)]:
                self.assertEqual(gzip.decompress((folder/side/(name+'.gz')).read_bytes()),path.read_bytes())
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertFalse((self.manager.state/'last-sync.json').exists())
        self.assertFalse((self.manager.state/'writeback.json').exists())

    def test_manual_failure_resumes_writer_and_retains_incomplete_backup(self):
        resumed=[]
        @contextlib.contextmanager
        def pause(root):
            try:yield
            finally:resumed.append(True)
        with patch.object(nv,'quiesced',pause),patch.object(nv,'save_snapshot',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaises(OSError):backups.manual_backup(self.manager)
        self.assertEqual(resumed,[True]);self.assertFalse(self.manager.backups()['entries'][0]['complete'])

    def test_download_roundtrip_and_single_owned_ram_cache(self):
        result=backups.manual_backup(self.manager);folder=self.manager.state/'backups'/result['id']
        before={p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        # Exporting a stored backup must never touch live NV or reinitialize it.
        with patch.object(self.manager,'map',side_effect=AssertionError('raw NV read')),patch.object(nv,'working',side_effect=AssertionError('live NV read')):
            first=backups.prepare_download(self.manager,{'id':result['id']})['download']
            second=backups.prepare_download(self.manager,{'id':result['id']})['download']
        self.assertNotEqual(first['path'],second['path']);self.assertFalse((self.root/first['path'].lstrip('/')).exists())
        output=self.root/second['path'].lstrip('/')
        self.assertEqual(len(list(output.parent.glob('export-*.tar.gz'))),1)
        self.assertEqual(len(list(output.parent.glob('*.part'))),0)
        with tarfile.open(output,'r:gz') as archive:
            prefix='e5-nv-backup-'+result['id']+'/'
            manifest=json.load(archive.extractfile(prefix+'download-manifest.json'))
            self.assertEqual(set(manifest['files']),set(before))
            for name,raw in before.items():
                self.assertEqual(archive.extractfile(prefix+'files/'+name).read(),raw)
                self.assertEqual(manifest['files'][name]['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(before,{p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()})

    def test_recovery_paths_and_symlinks_blocked(self):
        result=backups.manual_backup(self.manager);ident=result['id']
        with self.assertRaisesRegex(nv.NVError,'nv_invalid_request'):backups.prepare_download(self.manager,{'id':'../outside'})
        nv.atomic_json(self.manager.state/'writeback.json',{'backup':'etc/e5-nv/backups/'+ident})
        with self.assertRaisesRegex(nv.NVError,'nv_recovery_pending'):backups.prepare_download(self.manager,{'id':ident})
        with self.assertRaisesRegex(nv.NVError,'nv_recovery_pending'):backups.manual_backup(self.manager)
        (self.manager.state/'writeback.json').unlink()
        (self.manager.state/'backups'/ident/'escape').symlink_to(self.store/'nr_fixnv1_a')
        with self.assertRaisesRegex(nv.NVError,'nv_unsafe_path'):backups.prepare_download(self.manager,{'id':ident})

    def test_export_failure_retains_previous_download_and_cleans_partial(self):
        result=backups.manual_backup(self.manager);request={'id':result['id']}
        first=backups.prepare_download(self.manager,request)['download']
        with patch.object(backups.tarfile,'open',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaisesRegex(nv.NVError,'nv_backup_space'):backups.prepare_download(self.manager,request)
        output=self.root/first['path'].lstrip('/')
        self.assertTrue(output.exists());self.assertEqual(len(list(output.parent.iterdir())),1)

    def test_async_manual_and_download_have_no_sync_confirmation(self):
        with patch.object(nv.subprocess,'Popen'):
            started=self.manager.start({},'manual_backup')
        request=self.manager.ram/('request-'+started['job']['id']+'.json')
        nv.run_worker(request,self.manager)
        job=nv.read_json(self.manager.ram/'job.json',{})
        self.assertEqual(job['state'],'complete');self.assertTrue(job['result']['manual_backup'])
        with patch.object(nv.subprocess,'Popen'):
            started=self.manager.start({'id':job['result']['id']},'prepare_download')
        request=self.manager.ram/('request-'+started['job']['id']+'.json')
        nv.run_worker(request,self.manager)
        job=nv.read_json(self.manager.ram/'job.json',{})
        self.assertEqual(job['state'],'complete');self.assertTrue(job['result']['download'])
        self.assertFalse((self.manager.state/'last-sync.json').exists())

    def test_download_acl_is_authenticated_and_narrow(self):
        acl=json.loads((fixtures.TOP/'openwrt/luci-app-t551m/root/usr/share/rpcd/acl.d/e5-nv.json').read_text())['e5-nv']
        self.assertEqual(acl['read']['cgi-io'],['download'])
        self.assertEqual(acl['read']['file'],{'/tmp/e5-nv-download/export-*.tar.gz':['read']})

    def test_legacy_uncompressed_download_keeps_conflicting_metadata_names(self):
        ident='20261025-123456-012345abcdef'
        folder=self.manager.state/'backups'/ident;folder.mkdir(parents=True)
        content={'record.json':b'{"complete":true}', 'README.txt':b'user backup notes',
                 'download-manifest.json':b'previous manifest', 'source/nr_fixnv1_a':fixtures.image()}
        for name,raw in content.items():
            path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        result=backups.prepare_download(self.manager,{'id':ident})['download']
        with tarfile.open(self.root/result['path'].lstrip('/'),'r:gz') as archive:
            prefix='e5-nv-backup-'+ident+'/'
            self.assertEqual(set(json.load(archive.extractfile(prefix+'download-manifest.json'))['files']),set(content))
            for name,raw in content.items():self.assertEqual(archive.extractfile(prefix+'files/'+name).read(),raw)

    def test_export_source_change_fails_without_publishing_or_losing_prior_cache(self):
        result=backups.manual_backup(self.manager);request={'id':result['id']}
        first=backups.prepare_download(self.manager,request)['download']
        real_digest=nv.digest;calls=0
        def changed(path):
            nonlocal calls
            calls+=1
            return '0'*64 if calls==2 else real_digest(path)
        with patch.object(nv,'digest',side_effect=changed):
            with self.assertRaisesRegex(nv.NVError,'nv_snapshot_changed'):backups.prepare_download(self.manager,request)
        output=self.root/first['path'].lstrip('/')
        self.assertTrue(output.exists());self.assertEqual(list(output.parent.iterdir()),[output])

    def test_manual_and_download_reject_duplicate_launches_and_upgrade_lock(self):
        with patch.object(nv.subprocess,'Popen') as launch:
            self.manager.start({},'manual_backup')
            for operation,data in [('manual_backup',{}),('prepare_download',{'id':'20261025-123456-012345abcdef'})]:
                with self.assertRaisesRegex(nv.NVError,'nv_busy'):self.manager.start(data,operation)
            self.assertEqual(launch.call_count,1)
        with nv.maintenance_lock(self.root):
            with self.assertRaises(BlockingIOError):backups.manual_backup(self.manager)

    def test_manual_snapshots_all_models_and_both_firmware_slots(self):
        for profile in nv.PROFILES:
            for slot in ('a','b'):
                (self.root/'etc/e5/device-profile').write_text(profile)
                (self.root/'etc/e5/modem-slot').write_text(slot)
                result=backups.manual_backup(self.manager)
                folder=self.manager.state/'backups'/result['id']
                record=nv.read_json(folder/'record.json')
                self.assertEqual((record['profile'],record['firmware_slot']),(profile,slot))
                self.assertTrue(record['complete']);self.assertEqual(len(list(folder.glob('*/*.gz'))),18)


if __name__=='__main__':unittest.main()
