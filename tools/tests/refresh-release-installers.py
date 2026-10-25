#!/usr/bin/env python3
"""Installer refresh must preserve image bytes and checksum coverage."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
import zipfile

TOP=Path(__file__).resolve().parents[2]
helper=runpy.run_path(str(TOP/'tools/refresh-release-installers.py'))
runner=runpy.run_path(str(TOP/'tools/build-release.py'))


class Refresh(unittest.TestCase):
    def test_stream_refresh_preserves_firmware_and_updates_only_host_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'old.zip';target=root/'new.zip';tools=root/'tools.tar';tools.write_bytes(b'new tools')
            files={'files/boot.img':b'unchanged boot','files/openwrt.ext4.gz':b'unchanged image',
                   'files/part-write.sh':b'old writer','files/ext4-tools.tar':b'old tools',
                   'START-HERE.md':b'guide','OpenWrt-Diff-Studio.exe':b'GUI'}
            files['files/SHA256SUMS']=''.join(hashlib.sha256(v).hexdigest()+'  '+n+'\n' for n,v in files.items()).encode()
            with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
                for name,raw in files.items():z.writestr(name,raw)
            meta=helper['refresh'](source,target,tools,{'source_commit':'a'*40,'source_fingerprint':'b'*64})
            with zipfile.ZipFile(target) as z:
                self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),len(set(z.namelist())))
                for name in ('files/boot.img','files/openwrt.ext4.gz','OpenWrt-Diff-Studio.exe'):
                    self.assertEqual(z.read(name),files[name])
                self.assertEqual(z.read('files/ext4-tools.tar'),b'new tools')
                self.assertIn(b'flock',z.read('files/part-write.sh'))
                self.assertEqual(json.loads(z.read('files/INSTALLER-REVISION.json')),meta)
                sums={n:h for line in z.read('files/SHA256SUMS').decode().splitlines() for h,n in [line.split(None,1)]}
                self.assertEqual(set(sums),set(z.namelist())-{'files/SHA256SUMS'})
                for name,sha in sums.items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),sha)
            with self.assertRaisesRegex(ValueError,'already exists'):
                helper['refresh'](source,target,tools,{'source_commit':'a'*40})


if __name__=='__main__':unittest.main()
