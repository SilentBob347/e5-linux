"""Exercise real shared shell/Python UFS discovery against isolated sysfs trees."""
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
storage = runpy.run_path(str(HERE / 'block-storage.py'))


@unittest.skipUnless(os.name == 'posix', 'Linux shell/sysfs fixture required')
class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ('sys/class/block', 'etc/e5', 'usr/lib/e5', 'usr/libexec'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'etc/e5/storage-kind').write_text('ufs\n')
        shutil.copyfile(HERE.parents[1] / 'boot/storage.sh', self.root / 'usr/lib/e5/storage.sh')
        helper = self.root / 'usr/libexec/e5-ufs-id'
        helper.write_text('#!/bin/sh\necho ufs-descriptor-v1:1234:abcd\n')
        helper.chmod(0o755)

    def disk(self, name, bus='22000000.ufs'):
        device = self.root / ('sys/devices/platform/' + bus + '/host0/target0/0:0:0:0')
        disk = device / 'block' / name
        disk.mkdir(parents=True, exist_ok=True)
        (disk / 'device').symlink_to(device)
        (self.root / 'sys/class/block' / name).symlink_to(disk)
        return disk

    def part(self, disk, number, label):
        name = disk.name + str(number)
        node = disk / name; node.mkdir()
        (node / 'partition').write_text(str(number))
        (node / 'uevent').write_text('DEVNAME=' + name + '\nPARTNAME=' + label + '\n')
        (self.root / 'sys/class/block' / name).symlink_to(node)

    def tearDown(self):
        self.tmp.cleanup()

    def test_internal_userdata_selects_only_its_ufs_lun(self):
        disk = self.disk('sda'); self.part(disk, 1, 'userdata'); self.part(disk, 2, 'nr_fixnv1_a')
        usb = self.disk('sdb', 'usb1'); self.part(usb, 1, 'userdata'); self.part(usb, 2, 'nr_fixnv1_a')
        self.assertEqual([p.parent.name for p in storage['entries'](self.root)], ['sda1', 'sda2'])
        expected = hashlib.sha256(b'ufs-descriptor-v1:1234:abcd:0').hexdigest()[:32]
        self.assertEqual(storage['identity'](self.root), expected)

    def test_two_internal_userdata_luns_are_not_guessed(self):
        for name in ('sda', 'sdc'):
            self.part(self.disk(name), 1, 'userdata')
        with self.assertRaises(subprocess.CalledProcessError):
            storage['entries'](self.root)

    def test_no_userdata_and_unknown_storage_fail(self):
        self.disk('sda')
        with self.assertRaises(subprocess.CalledProcessError):
            storage['entries'](self.root)
        (self.root / 'etc/e5/storage-kind').write_text('usb')
        with self.assertRaises(RuntimeError):
            storage['entries'](self.root)

    def test_emmc_path_is_unchanged(self):
        (self.root / 'etc/e5/storage-kind').unlink()
        entry = self.root / 'sys/class/block/mmcblk0p2/uevent'
        entry.parent.mkdir(); entry.write_text('PARTNAME=nr_fixnv1_a\n')
        self.assertEqual(storage['entries'](self.root), [entry])


if __name__ == '__main__':
    unittest.main()
