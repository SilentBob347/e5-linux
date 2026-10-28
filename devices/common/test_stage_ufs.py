"""UFS roots must carry the source-matched static identity dependency."""
import hashlib
import json
from pathlib import Path
import runpy
import struct
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]
stage = runpy.run_path(str(Path(__file__).with_name('stage-ufs.py')))['stage']


class StageUFS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'root'
        marker = self.root/'etc/e5/storage-kind'
        marker.parent.mkdir(parents=True)
        marker.write_text('ufs\n')
        self.helper = Path(self.tmp.name)/'ufs-id'
        elf = bytearray(120)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', elf, 18, 183)
        struct.pack_into('<Q', elf, 32, 64)
        struct.pack_into('<HH', elf, 54, 56, 1)
        struct.pack_into('<I', elf, 64, 1)
        self.helper.write_bytes(elf)
        self.receipt = {'format':1, 'kind':'ufs-descriptor-v1', 'static_arm64':True,
            'bytes':len(elf), 'sha256':hashlib.sha256(elf).hexdigest(),
            'source_sha256':hashlib.sha256((TOP/'tools/ufs-id.c').read_bytes()).hexdigest()}
        self.save()

    def save(self):
        self.helper.with_suffix('.build.json').write_text(json.dumps(self.receipt))

    def test_matching_static_dependency_is_staged_idempotently(self):
        stage(self.root, self.helper)
        stage(self.root, self.helper)
        self.assertEqual((self.root/'usr/libexec/e5-ufs-id').read_bytes(), self.helper.read_bytes())

    def test_stale_source_or_changed_binary_is_rejected(self):
        for field in ('source_sha256', 'sha256'):
            saved = self.receipt[field]
            self.receipt[field] = '0'*64
            self.save()
            with self.assertRaises(ValueError): stage(self.root, self.helper)
            self.receipt[field] = saved

    def test_wrong_storage_kind_or_destination_symlink_is_rejected(self):
        marker = self.root/'etc/e5/storage-kind'
        marker.write_text('emmc')
        with self.assertRaises(ValueError): stage(self.root, self.helper)
        marker.write_text('ufs')
        target = self.root/'usr/libexec/e5-ufs-id'
        target.parent.mkdir(parents=True)
        target.symlink_to(self.helper)
        with self.assertRaises(ValueError): stage(self.root, self.helper)


if __name__ == '__main__': unittest.main()
