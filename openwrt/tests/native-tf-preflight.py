#!/usr/bin/env python3
"""Exercise native TF preflight with disposable package files, no devices."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]


class Preflight(unittest.TestCase):
    def test_geometry_helper_is_required_before_boot_or_card_operations(self):
        cases=[(False,'e5','green',True,'a'),(True,'k1','green',False,'b'),
               (True,'yuanhang41s','green',False,'a')]
        cases += [(True,profile,state,True,slot)
                  for profile in ('e5','m8','t551m','t512n','yuanhang41s','k1')
                  for state in ('orange','green','yellow','red','') for slot in ('a','b')]
        for include,profile,verified,allowed,slot in cases:
            with self.subTest(include=include,profile=profile,verified=verified),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);package=root/'package';state=root/'state'
                (package/'files').mkdir(parents=True);state.mkdir()
                model = {'m8':'M8','t551m':'T551M','t512n':'T512N','yuanhang41s':'ZTE 7546N','k1':'angelcare K1'}.get(profile,'E5')
                (package/'files/tf-install.env').write_text(f'PROFILE={profile}\nANDROID_MODEL="{model}"\nBOOT_BYTES=4096\nSLOT_ROLES_VERSION=1\n')
                node=root/'dev/block/by-name';node.mkdir(parents=True)
                for n in ('boot_a','boot_b','misc'):(node/n).touch()
                script=(TOP/'openwrt/bundle/magisk-tf-install.sh').read_text()
                script=script.replace('/dev/block',str(root/'dev/block')).replace('/data/e5linux',str(root/'data'))
                script=script.replace('[ -b ','[ -f ')
                with tarfile.open(package/'files/ext4-tools.tar','w') as tar:
                    for name in ['lib/ld-musl-aarch64.so.1','usr/sbin/e2fsck','usr/sbin/resize2fs','SHA256SUMS']+(['ext4-geometry.sh'] if include else []):
                        info=tarfile.TarInfo(name);info.size=1
                        tar.addfile(info,__import__('io').BytesIO(b'x'))
                stop=package/'files/e5-bootctl'
                stop.write_text('#!/bin/sh\ntouch "$STATE/reached-boot-check"\nexit 21\n');stop.chmod(0o755)
                code='''id(){ echo 0; }
getprop(){ case "$1" in ro.product.model) echo "$TEST_MODEL";; ro.product.device) echo "$TEST_BOARD";; ro.boot.slot_suffix) echo "_$TEST_SLOT";; ro.boot.verifiedbootstate) echo "$TEST_VERIFIED";; esac; }
sha256sum(){ return 0; }
blockdev(){ echo 4096; }
'''+script+'\npreflight\n'
                # Library loading returns before main; the appended preflight is explicit.
                fixture=root/'library.sh';fixture.write_text(code)
                harness='. "$LIB"; preflight'
                board=('ums9157_2h10' if profile=='k1' else 'P720S11') if allowed else 'wrong-board'
                env=dict(os.environ,LIB=str(fixture),E5_TF_LIB='1',P=str(package),STATE=str(state),TEST_MODEL=model,TEST_VERIFIED=verified,TEST_SLOT=slot,TEST_BOARD=board)
                result=subprocess.run(['busybox','ash','-ec',harness],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual((state/'reached-boot-check').exists(),include and allowed,result.stdout+result.stderr)
                self.assertEqual('missing ext4 tool: ext4-geometry.sh' in result.stderr,not include and allowed)
                if not allowed:
                    self.assertIn('unknown K1 board' if profile=='k1' else 'unknown 41S board',result.stderr)


if __name__=='__main__':unittest.main()
