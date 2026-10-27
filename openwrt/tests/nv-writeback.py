#!/usr/bin/env python3
"""Synthetic VN/INDX2 transactions; never use a physical device's NV."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOP/'openwrt/luci-app-t551m/root/usr/lib/e5'))
import nv_persistence as nv
import nv_writeback as wb
from nv_format import FixedNV, FormatError, PROTECTED, checksum, decode_imei


def imei(value):
    digits = 'A'+value
    return bytes(int(digits[i+1]+digits[i], 16) for i in range(0, 16, 2))


def record(ident, value):
    return struct.pack('<HH', ident, len(value))+value+b'\xa5'*((-len(value))%4)


def image(value=1, generation=7, identity='123456789012345', tail=b'original tail', signed=False, prefix=b''):
    protocol = (prefix+record(5, imei(identity))+record(0x179, imei('987654321098765'))+
                record(0x1a6, b'signature')+record(0x100, bytes([value])*8)+record(0xfffe, b'fill'))
    radio = record(0x200, bytes([value])*13)+record(0xfffe, b'pad!')
    index = bytearray(56); index[:4]=b'INDX'; struct.pack_into('<H', index, 6, 2)
    index[8:12]=b'PSCP'; index[32:36]=b'PHY\0'
    struct.pack_into('<II', index, 24, 64, len(protocol))
    struct.pack_into('<II', index, 48, 64+len(protocol), len(radio))
    payload = (struct.pack('<I', generation)+record(0, bytes(index))+protocol+radio+
               record(0x300, b'ext')+b'\xff\xff\x00\x00').ljust(512, b'\xff')
    header = bytearray(struct.pack('<4I', 0x4e56, len(payload), checksum(payload), 101).ljust(512,b'\0'))
    if signed: header[16:48]=hashlib.sha256(payload).digest()
    return (bytes(header)+payload+tail).ljust(4096,b'\x5a')


def runtime_image(value):
    payload=b'VNTS'+bytes([value])*508
    return (struct.pack('<4I',0x4e56,len(payload),checksum(payload),101).ljust(512,b'\0')+payload).ljust(4096,b'\0')


def delta_image(value, name=b'hw_rffeid001', version=1):
    content=struct.pack('<HHH',0x100,0,4)+bytes([value])*4+b'\xff\xff'
    header=name.ljust(20,b'\0')+struct.pack('<HI',version,26+len(content))
    return (header+content).ljust(4096,b'\0')


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.store=self.root/'opt/e5/nv'; self.store.mkdir(parents=True)
        (self.root/'etc/e5').mkdir(parents=True)
        (self.root/'etc/e5/device-profile').write_text('e5')
        (self.root/'etc/e5/modem-slot').write_text('b')
        (self.root/'sys/class/block/mmcblk0/device').mkdir(parents=True)
        (self.root/'sys/class/block/mmcblk0/device/cid').write_text('1'*32)
        (self.root/'proc/sys/kernel/random').mkdir(parents=True)
        (self.root/'proc/sys/kernel/random/boot_id').write_text('synthetic-boot')
        self.devices={}
        for name in nv.NAMES:
            data=image() if name.startswith('nr_fixnv') else b'\0'*4096
            source=self.root/('raw-'+name);source.write_bytes(data);self.devices[name]=source
            (self.store/name).write_bytes(data)
        nv.atomic_json(self.store/'factory-sha256.json',{n:nv.digest(p) for n,p in self.devices.items()})
        self.manager=nv.Manager(self.root,self.devices)

    def changed(self):
        for name in ('nr_fixnv1_b','nr_fixnv2_b'):
            (self.store/name).write_bytes(image(2,identity='111111111111111',tail=b'working tail'))

    def saved(self):
        self.manager.preview('to-original')
        return nv.read_json(self.manager.ram/'preview.json')

    def journal(self): return nv.read_json(self.manager.state/'writeback.json')

    def request(self):
        p=self.manager.preview('to-original')
        return dict(direction='to-original',confirmation='yes',token=p['token'],conflict_ack=p['conflict'])

    def test_decode_two_imeis_no_validity_guess(self):
        parsed=FixedNV(image())
        self.assertEqual(parsed.imeis(),{'sim1':'123456789012345','sim2':'987654321098765'})
        for bad in (b'',b'\0'*8,b'\xff'*8,b'\xab'*8): self.assertIsNone(decode_imei(bad))

    def test_imei_items_can_move_with_variable_length_preceding_items(self):
        original = FixedNV(image())
        for size in (1, 5, 29, 81):
            moved = FixedNV(image(prefix=record(0x110,b'Z'*size)))
            self.assertNotEqual(original.items[5][0], moved.items[5][0])
            self.assertNotEqual(original.items[0x179][0], moved.items[0x179][0])
            self.assertEqual(original.imeis(), moved.imeis())

    def test_runtime_firmware_slot_survives_missing_old_install_metadata(self):
        (self.root/'etc/e5/modem-slot').unlink()
        run = self.root/'run'; run.mkdir()
        (run/'e5-cmdline.android').write_text('androidboot.slot_suffix=_a sprdboot.slot_suffix=_a console=tty0')
        (run/'e5-bootconfig.android').write_text('androidboot.slot_suffix = "_a"\n')
        (self.root/'proc/cmdline').write_text('sprdboot.slot_suffix=_b')
        (self.root/'proc/bootconfig').write_text('androidboot.slot_suffix = "_b"\n')
        self.assertEqual(self.manager.identity(), ('e5','a'))
        state = self.manager.status()
        self.assertTrue(state['original_validated'])
        self.assertTrue(state['work_validated'])
        self.assertEqual(state['imei']['working'], FixedNV(image()).imeis())
        self.assertEqual(state['imei']['original'], FixedNV(image()).imeis())

    def test_runtime_b_is_not_guessed_from_linux_a(self):
        (self.root/'etc/e5/modem-slot').unlink()
        proc = self.root/'opt/e5/android/proc'; proc.mkdir(parents=True)
        (proc/'cmdline').write_text('sprdboot.slot_suffix=_b androidboot.slot_suffix=_b')
        (self.root/'proc/cmdline').write_text('sprdboot.slot_suffix=_a')
        self.assertEqual(self.manager.identity(), ('e5','b'))

    def test_unknown_modem_slot_cannot_use_linux_boot_slot(self):
        (self.root/'etc/e5/modem-slot').unlink()
        (self.root/'proc/cmdline').write_text('sprdboot.slot_suffix=_b')
        with self.assertRaisesRegex(nv.NVError, 'nv_slot_unknown'):
            self.manager.identity()

    def test_firmware_metadata_can_identify_an_offline_old_root(self):
        (self.root/'etc/e5/modem-slot').unlink()
        path = self.root/'lib/firmware/android-firmware-slot'; path.parent.mkdir(parents=True)
        path.write_text('a\n')
        self.assertEqual(self.manager.identity(), ('e5','a'))

    def test_current_policy_and_explicit_choice_take_priority_over_import_metadata(self):
        path = self.root/'lib/firmware/android-firmware-slot'; path.parent.mkdir(parents=True)
        path.write_text('a\n')
        self.assertEqual(self.manager.identity(), ('e5','b'))
        (self.root/'etc/e5/modem-slot').write_text('current\n')
        (self.root/'proc/cmdline').write_text('sprdboot.slot_suffix=_b')
        (self.root/'proc/bootconfig').write_text('androidboot.slot_suffix = "_b"\n')
        self.assertEqual(self.manager.identity(), ('e5','b'))

    def test_conflicting_runtime_sources_or_explicit_policy_disable_sync(self):
        run = self.root/'run'; run.mkdir()
        (run/'e5-cmdline.android').write_text('sprdboot.slot_suffix=_a')
        with self.assertRaisesRegex(nv.NVError, 'nv_slot_conflict'):
            self.manager.identity()
        (self.root/'etc/e5/modem-slot').unlink()
        (run/'e5-bootconfig.android').write_text('androidboot.slot_suffix = "_b"\n')
        with self.assertRaisesRegex(nv.NVError, 'nv_slot_conflict'):
            self.manager.identity()
        state = self.manager.status()
        for key in ('reason', 'import_reason', 'export_reason'):
            self.assertEqual(state[key], 'nv_slot_conflict')
        self.assertFalse(state['can_import'])
        self.assertFalse(state['can_export'])

    def test_original_mapping_failure_does_not_hide_working_imeis(self):
        with patch.object(self.manager, 'map', side_effect=nv.NVError('nv_original_not_protected')):
            identities = wb.read_imeis(self.manager)
            self.assertEqual(identities['working'], FixedNV(image()).imeis())
            self.assertNotIn('original', identities)

    def test_partition_numbers_are_discovered_from_sysfs_names(self):
        for index, name in enumerate(nv.NAMES, 81):
            block = self.root/f'sys/class/block/mmcblk0p{index}'; block.mkdir(parents=True)
            (block/'uevent').write_text(f'DEVNAME=mmcblk0p{index}\nPARTNAME={name}\n')
            device = self.root/f'dev/mmcblk0p{index}';device.parent.mkdir(exist_ok=True);device.write_bytes(b'fixture')
        with patch.object(nv.stat,'S_ISBLK',return_value=True), patch.object(nv.fcntl,'ioctl',return_value=struct.pack('i',1)):
            mapped = nv.Manager(self.root).map()
        self.assertEqual({name:path.name for name,path in mapped.items()},
                         {name:f'mmcblk0p{index}' for index,name in enumerate(nv.NAMES,81)})

    def test_full_copy_does_not_reencode_headers_generation_or_tail(self):
        for signed in (False,True):
            data=image(9,generation=0xffffffff,identity='111111111111111',tail=b'full source tail',signed=signed)
            (self.store/'nr_fixnv1_a').write_bytes(data)
            result=wb.writeback(self.manager,self.saved())
            self.assertTrue(result['ok']);self.assertEqual(self.devices['nr_fixnv1_a'].read_bytes(),data)
            self.assertEqual(FixedNV.read(self.devices['nr_fixnv1_a']).generation,0xffffffff)

    def test_bad_checksum_unknown_header_index_and_duplicate_id_rejected(self):
        original=image()
        for offset in (8,16,512+8,512+64):
            bad=bytearray(original);bad[offset]^=1
            if offset>=512:struct.pack_into('<I',bad,8,checksum(bad[512:1024]))
            with self.assertRaises(FormatError):FixedNV(bad)

    def test_unknown_framing_rejected(self):
        with self.assertRaises(FormatError):FixedNV(b'\0'*4096)

    def test_status_shows_two_sets_imeis_and_business_difference_without_hashes(self):
        self.changed();s=self.manager.status()
        self.assertTrue(s['can_export']);self.assertTrue(s['validated'])
        self.assertEqual(s['imei']['original']['sim1'],'123456789012345')
        self.assertEqual(s['imei']['working']['sim1'],'111111111111111')
        self.assertEqual(s['comparison']['items'],2);self.assertFalse(s['fixed_equal'])
        text=json.dumps(s);self.assertNotIn('sha256',text);self.assertNotIn(nv.digest(self.devices['nr_fixnv1_b']),text)

    def test_bad_runtime_disables_sync_but_does_not_hide_valid_fixed_identities(self):
        (self.store/'nr_runtimenv1').write_bytes(b'bad runtime')
        status=self.manager.status()
        self.assertFalse(status['can_import']);self.assertFalse(status['can_export'])
        self.assertEqual(status['imei']['original']['sim2'],'987654321098765')
        self.assertEqual(status['imei']['working']['sim1'],'123456789012345')

    def test_all_six_profiles_dynamic_slots_and_no_other_partitions_changed(self):
        for profile in nv.PROFILES:
            for slot in ('a','b'):
                with self.subTest(profile=profile,slot=slot):
                    (self.root/'etc/e5/device-profile').write_text(profile)
                    (self.root/'etc/e5/modem-slot').write_text(slot)
                    for name,path in self.devices.items():
                        if name.startswith('nr_fixnv'):path.write_bytes(image());(self.store/name).write_bytes(image())
                    nv.atomic_json(self.store/'factory-sha256.json',{n:nv.digest(p) for n,p in self.devices.items()})
                    for i,name in enumerate(wb.FIXED):
                        (self.store/name).write_bytes(image(i+3,identity='111111111111111',tail=('work-'+name).encode()))
                    before={n:p.read_bytes() for n,p in self.devices.items()}
                    with patch.object(nv.subprocess,'run') as run:result=self.manager.sync(self.request())
                    run.assert_called_once();self.assertTrue(result['ok'])
                    selected=wb.FIXED
                    for n,p in self.devices.items():
                        if n not in selected:self.assertEqual(p.read_bytes(),before[n])
                        else:
                            self.assertEqual(p.read_bytes(),(self.store/n).read_bytes())
                            self.assertEqual(FixedNV.read(p).imeis()['sim1'],'111111111111111')
                    self.assertFalse(self.journal());self.assertTrue(self.manager.status()['fixed_equal'])

    def test_backup_first_and_full_readback_copy_working_tails_exactly(self):
        self.changed();self.devices['nr_fixnv2_b'].write_bytes(image(tail=b'redundant tail'))
        saved=self.saved();order=[]
        class Writer(wb.PairWriter):
            def write(inner,source,target,expected):
                order.append(target);super().write(source,target,expected)
        wb.writeback(self.manager,saved,writer=Writer(True))
        self.assertEqual(order,[self.devices['nr_fixnv2_b'],self.devices['nr_fixnv1_b']])
        self.assertEqual(self.devices['nr_fixnv2_b'].read_bytes(),(self.store/'nr_fixnv2_b').read_bytes())

    def test_failure_after_partial_primary_write_restores_both_and_origin(self):
        self.changed();before={n:p.read_bytes() for n,p in self.devices.items()};origin=(self.store/'factory-sha256.json').read_bytes()
        class Writer(wb.PairWriter):
            def write(inner,source,target,expected):
                if target==self.devices['nr_fixnv1_b']:
                    target.write_bytes(b'partial'+target.read_bytes()[7:]);raise OSError('injected write failure')
                super().write(source,target,expected)
        with self.assertRaises(OSError):wb.writeback(self.manager,self.saved(),writer=Writer(True))
        self.assertEqual(before,{n:p.read_bytes() for n,p in self.devices.items()})
        self.assertEqual(nv.read_json(self.store/'factory-sha256.json'),json.loads(origin))
        self.assertFalse(self.journal())

    def test_metadata_failure_after_raw_commit_restores_provenance_too(self):
        self.changed();before={n:p.read_bytes() for n,p in self.devices.items()};origin=nv.read_json(self.store/'factory-sha256.json')
        real=nv.atomic_json
        def write(path,data):
            if Path(path).name=='last-sync.json':raise OSError('injected record failure')
            return real(path,data)
        with patch.object(nv,'atomic_json',side_effect=write),self.assertRaises(OSError):wb.writeback(self.manager,self.saved())
        self.assertEqual(before,{n:p.read_bytes() for n,p in self.devices.items()})
        self.assertEqual(origin,nv.read_json(self.store/'factory-sha256.json'));self.assertFalse(self.journal())

    def power_loss(self,count):
        self.changed();before={n:p.read_bytes() for n,p in self.devices.items()};writes=[]
        class Loss(BaseException): pass
        class Writer(wb.PairWriter):
            def write(inner,source,target,expected):
                if len(writes)==count:raise Loss()
                super().write(source,target,expected);writes.append(target)
        if count==2:
            real=nv.atomic_json
            def output(path,value):
                if Path(path)==self.store/'factory-sha256.json':raise Loss()
                real(path,value)
            with patch.object(nv,'atomic_json',side_effect=output),self.assertRaises(Loss):
                wb.writeback(self.manager,self.saved(),writer=Writer(True))
        else:
            with self.assertRaises(Loss):wb.writeback(self.manager,self.saved(),writer=Writer(True))
        self.assertTrue(self.journal());return before

    def test_power_loss_after_backup_restores_before_next_modem_start(self):
        before=self.power_loss(1);wb.recover_writeback(self.manager)
        self.assertEqual(before,{n:p.read_bytes() for n,p in self.devices.items()});self.assertFalse(self.journal())
        self.assertFalse(nv.read_json(self.manager.state/'last-sync.json')['ok'])

    def test_power_loss_after_pair_commit_finalizes_and_updates_source_record(self):
        self.power_loss(2);wb.recover_writeback(self.manager)
        self.assertTrue(nv.read_json(self.manager.state/'last-sync.json')['ok']);self.assertFalse(self.journal())
        for name in ('nr_fixnv1_b','nr_fixnv2_b'):
            self.assertEqual(nv.digest(self.devices[name]),nv.read_json(self.store/'factory-sha256.json')[name])

    def test_recovery_rejects_other_device_slot_and_tampered_backup_without_writes(self):
        self.power_loss(1);after={n:p.read_bytes() for n,p in self.devices.items()}
        cid=self.root/'sys/class/block/mmcblk0/device/cid';cid.write_text('2'*32)
        with self.assertRaisesRegex(FormatError,'nv_writeback_recovery_mismatch'):wb.recover_writeback(self.manager)
        cid.write_text('1'*32)
        journal=self.journal();backup=self.root/journal['backup'];(backup/'source/nr_fixnv1_b.gz').write_bytes(b'corrupt gzip')
        with self.assertRaises((nv.NVError,OSError)):wb.recover_writeback(self.manager)
        self.assertEqual(after,{n:p.read_bytes() for n,p in self.devices.items()});self.assertTrue(self.journal())

    def test_bad_new_image_backup_does_not_prevent_old_snapshot_recovery(self):
        before=self.power_loss(1);record=self.journal();backup=self.root/record['backup']
        (backup/'work/nr_fixnv1_b.gz').write_bytes(b'broken gzip')
        wb.recover_writeback(self.manager)
        self.assertEqual(before,{n:p.read_bytes() for n,p in self.devices.items()})
        self.assertFalse(self.journal())

    def test_existing_v1_raw_transaction_can_recover_after_program_upgrade(self):
        backup=self.manager.state/'backups/20261025-123456-012345abcdef'
        (backup/'source').mkdir(parents=True);(backup/'candidate').mkdir()
        names=['nr_fixnv1_b','nr_fixnv2_b'];before={};after={}
        for name in names:
            (backup/'source'/name).write_bytes(image());(backup/'candidate'/name).write_bytes(image(2))
            before[name]=nv.digest(backup/'source'/name);after[name]=nv.digest(backup/'candidate'/name)
        nv.atomic_json(backup/'factory-sha256.json',nv.read_json(self.store/'factory-sha256.json'))
        record={'format':1,'identity':wb.device_identity(self.manager),'backup':backup.relative_to(self.root).as_posix(),
                'names':names,'before':before,'after':after,'origin_sha256':nv.digest(backup/'factory-sha256.json')}
        self.devices['nr_fixnv2_b'].write_bytes(image(2));nv.atomic_json(self.manager.state/'writeback.json',record)
        wb.recover_writeback(self.manager)
        for name in names:self.assertEqual(self.devices[name].read_bytes(),image())
        self.assertFalse(self.journal())

    def test_pending_transaction_cannot_be_deleted_imported_or_archived(self):
        self.power_loss(1);row=self.manager.backups()['entries'][0];self.assertTrue(row['protected'])
        for operation in (lambda:self.manager.delete_backup({'id':row['id'],'confirmation':'yes'}),
                          lambda:self.manager.compress_backup({'id':row['id'],'confirmation':'yes'}),
                          lambda:self.manager.preview('from-original'),lambda:nv.archive_quiet(self.root,__import__('io').BytesIO())):
            with self.assertRaisesRegex(nv.NVError,'nv_recovery_pending'):operation()

    def test_backup_delete_typed_confirmation_and_traversal_and_only_selected(self):
        self.changed();wb.writeback(self.manager,self.saved());row=self.manager.backups()['entries'][0]
        before={n:p.read_bytes() for n,p in self.devices.items()}
        for request in ({'id':row['id'],'confirmation':'YES'},{'id':'../../opt/e5/nv','confirmation':'yes'}):
            with self.assertRaises(nv.NVError):self.manager.delete_backup(request)
        self.manager.delete_backup({'id':row['id'],'confirmation':'yes'})
        self.assertFalse(self.manager.backups()['entries']);self.assertEqual(before,{n:p.read_bytes() for n,p in self.devices.items()})

    def test_runtime_changes_do_not_expire_confirmation_but_fixed_changes_do(self):
        self.changed();request=self.request();saved=nv.read_json(self.manager.ram/'preview.json')['state']
        # A valid non-empty runtime uses the existing generic wrapper validation.
        (self.store/'nr_runtimenv1').write_bytes(image(2))
        self.assertTrue(self.manager.preview_matches(saved,self.manager.inspect()))
        (self.store/'nr_fixnv1_b').write_bytes(image(3))
        self.assertFalse(self.manager.preview_matches(saved,self.manager.inspect()))

    def test_full_file_copy_includes_source_identity_after_confirmation(self):
        (self.store/'nr_fixnv1_b').write_bytes(image(identity='111111111111111'))
        before={n:p.read_bytes() for n,p in self.devices.items()}
        result=wb.writeback(self.manager,self.saved());self.assertFalse(result['unchanged'])
        self.assertEqual(self.devices['nr_fixnv1_b'].read_bytes(),(self.store/'nr_fixnv1_b').read_bytes())
        self.assertTrue(all(p.read_bytes()==before[n] for n,p in self.devices.items() if n!='nr_fixnv1_b'))

    def test_byte_identical_confirmed_web_writeback_does_not_stop_modem(self):
        with patch.object(nv.subprocess,'run') as stop:
            outcome=self.manager.sync(self.request())
        stop.assert_not_called();self.assertTrue(outcome['unchanged']);self.assertFalse(outcome['reboot_required'])

    def test_valid_full_container_does_not_require_record_merge_layout(self):
        data=bytearray(image(4));struct.pack_into('<I',data,12,1)
        for name in wb.FIXED:(self.store/name).write_bytes(data)
        with patch.object(nv.subprocess,'run'):self.manager.sync(self.request())
        for name in wb.FIXED:self.assertEqual(self.devices[name].read_bytes(),bytes(data))

    def test_runtime_uses_final_flushed_data_after_stop_not_preview_data(self):
        for name in ('nr_runtimenv1','nr_runtimenv2'):(self.store/name).write_bytes(runtime_image(3))
        request=self.request()
        def stop(*a,**k):
            for name in ('nr_runtimenv1','nr_runtimenv2'):(self.store/name).write_bytes(runtime_image(7))
        with patch.object(nv.subprocess,'run',side_effect=stop) as command:self.manager.sync(request)
        command.assert_called_once()
        for name in ('nr_runtimenv1','nr_runtimenv2'):self.assertEqual(self.devices[name].read_bytes(),runtime_image(7))

    def test_uninitialized_zero_runtime_is_valid_full_image(self):
        self.devices['nr_runtimenv1'].write_bytes(runtime_image(3))
        with patch.object(nv.subprocess,'run'):result=self.manager.sync(self.request())
        self.assertTrue(result['ok']);self.assertEqual(self.devices['nr_runtimenv1'].read_bytes(),b'\0'*4096)

    def test_delta_value_changes_are_supported_with_same_verified_layout(self):
        source=self.devices['nr_deltanv_a'];source.write_bytes(delta_image(1))
        nv.atomic_json(self.store/'factory-sha256.json',{n:nv.digest(p) for n,p in self.devices.items()})
        (self.store/'nr_deltanv_a').write_bytes(delta_image(2))
        plan=self.manager.preview('to-original');self.assertEqual(plan['writeback_checks']['nr_deltanv_a'],'delta-layout')
        with patch.object(nv.subprocess,'run'):result=self.manager.sync(self.request())
        self.assertEqual(source.read_bytes(),delta_image(2));self.assertFalse(result['skipped_files'])

    def test_unknown_delta_board_or_calinv_change_is_visible_and_not_written(self):
        self.changed();source=self.devices['nr_deltanv_a'];source.write_bytes(delta_image(1))
        nv.atomic_json(self.store/'factory-sha256.json',{n:nv.digest(p) for n,p in self.devices.items()})
        (self.store/'nr_deltanv_a').write_bytes(delta_image(2,name=b'other_board'))
        (self.store/'calinv').write_bytes(b'unknown new calibration'.ljust(4096,b'\0'))
        before={n:p.read_bytes() for n,p in self.devices.items()}
        plan=self.manager.preview('to-original');self.assertEqual(plan['writeback_blocked'],['nr_deltanv_a','calinv'])
        self.assertTrue(self.manager.status()['can_export'])
        with patch.object(nv.subprocess,'run'):result=self.manager.sync(self.request())
        self.assertEqual(result['skipped_files'],['nr_deltanv_a','calinv'])
        self.assertEqual(source.read_bytes(),before['nr_deltanv_a']);self.assertEqual(self.devices['calinv'].read_bytes(),before['calinv'])
        self.assertEqual(self.devices['nr_fixnv1_b'].read_bytes(),(self.store/'nr_fixnv1_b').read_bytes())

    def test_original_provenance_calinv_and_checksum_calinv_can_write_back(self):
        self.devices['calinv'].write_bytes(b'new Android calibration'.ljust(4096,b'\0'))
        plan=self.manager.preview('to-original');self.assertEqual(plan['writeback_checks']['calinv'],'original-snapshot')
        with patch.object(nv.subprocess,'run'):self.manager.sync(self.request())
        self.assertEqual(self.devices['calinv'].read_bytes(),b'\0'*4096)
        self.devices['calinv'].write_bytes(image(1));(self.store/'calinv').write_bytes(image(2))
        nv.atomic_json(self.store/'factory-sha256.json',{n:nv.digest(p) for n,p in self.devices.items()})
        plan=self.manager.preview('to-original');self.assertEqual(plan['writeback_checks']['calinv'],'vn-checksum')
        with patch.object(nv.subprocess,'run'):self.manager.sync(self.request())
        self.assertEqual(self.devices['calinv'].read_bytes(),image(2))

    def test_only_unverified_changes_neither_stop_modem_nor_claim_all_equal(self):
        (self.store/'calinv').write_bytes(b'unverified'.ljust(4096,b'\0'))
        with patch.object(nv.subprocess,'run') as stop:result=self.manager.sync(self.request())
        stop.assert_not_called();self.assertEqual(result['skipped_files'],['calinv']);self.assertTrue(result['unchanged'])

    def test_old_four_file_confirmation_cannot_expand_after_hot_update(self):
        self.changed();request=self.request();path=self.manager.ram/'preview.json';saved=nv.read_json(path)
        saved.pop('writeback_contract');saved['writeback_scope']=list(wb.FIXED);nv.atomic_json(path,saved)
        with patch.object(nv.subprocess,'run') as stop:
            with self.assertRaisesRegex(nv.NVError,'nv_preview_expired'):self.manager.sync(request)
            with self.assertRaisesRegex(nv.NVError,'nv_preview_expired'):self.manager.start(request)
        stop.assert_not_called()
        saved['writeback_contract']=wb.CONTRACT;nv.atomic_json(path,saved)
        with patch.object(nv.subprocess,'run') as stop:
            with self.assertRaisesRegex(nv.NVError,'nv_preview_expired'):self.manager.sync(request)
        stop.assert_not_called()

    def test_pending_backup_symlinks_and_bad_records_do_not_allow_deletion_escape(self):
        self.changed();outcome=wb.writeback(self.manager,self.saved());path=self.root/outcome['backup'].lstrip('/')
        nv.atomic_json(path/'record.json',[])
        self.assertFalse(self.manager.backups()['entries'][0]['complete'])
        (path/'outside').symlink_to(self.store,target_is_directory=True)
        with self.assertRaisesRegex(nv.NVError,'nv_unsafe_path'):
            self.manager.delete_backup({'id':path.name,'confirmation':'yes'})
        self.assertTrue(self.store.is_dir());self.assertTrue(path.is_dir())

    def test_completed_fast_worker_is_not_overwritten_by_launcher(self):
        request=self.request();manager=nv.Manager();manager.ram=self.manager.ram
        def launch(*args,**kwargs):
            job=nv.read_json(manager.ram/'job.json')
            nv.atomic_json(manager.ram/'job.json',{**job,'state':'complete','result':{'ok':True}})
            return object()
        with patch.object(nv.subprocess,'Popen',side_effect=launch):manager.start(request)
        self.assertEqual(manager.active_job()['state'],'complete')

    def test_worker_process_identity_detects_exit_and_pid_reuse(self):
        manager=nv.Manager();manager.ram=self.manager.ram
        ticks=(Path('/proc')/str(os.getpid())/'stat').read_text().rsplit(')',1)[1].split()[19]
        nv.atomic_json(manager.ram/'job.json',{'state':'running','pid':os.getpid(),'start_ticks':ticks})
        self.assertEqual(manager.active_job()['state'],'running')
        nv.atomic_json(manager.ram/'job.json',{'state':'running','pid':os.getpid(),'start_ticks':'wrong'})
        self.assertEqual(manager.active_job()['error'],'nv_worker_interrupted')


if __name__=='__main__':unittest.main()
