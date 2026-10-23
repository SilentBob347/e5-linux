"""Run boot readiness functions with private sysfs, device files and clock steps."""
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
SOURCE=(TOP/'boot/init').read_text()


def function(name):
    start=SOURCE.index(name+'() {');return SOURCE[start:SOURCE.index('\n}',start)+2]


class Readiness(unittest.TestCase):
    def run_case(self,name,ready_at=None,slot='a'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for d in ('dev','sys/class/block','sys/class/ieee80211','sys/module/wcn_bsp','sys/module/sprd_wlan_combo'):
                (root/d).mkdir(parents=True,exist_ok=True)
            busy=root/'busybox';busy.write_text('''#!/bin/sh
n=$(cat "$FIXTURE/ticks" 2>/dev/null || echo 0);n=$((n+1));echo "$n" > "$FIXTURE/ticks"
if [ "$n" = "${READY_AT:-none}" ]; then
    mkdir -p "$FIXTURE/sys/class/block/mmcblk0p3" "$FIXTURE/sys/class/block/mmcblk0p8" "$FIXTURE/sys/class/block/mmcblk0p9" "$FIXTURE/sys/class/ieee80211/phy0"
    printf 'PARTNAME=misc\n' > "$FIXTURE/sys/class/block/mmcblk0p3/uevent"
    printf 'PARTNAME=boot_a\n' > "$FIXTURE/sys/class/block/mmcblk0p8/uevent"
    printf 'PARTNAME=boot_b\n' > "$FIXTURE/sys/class/block/mmcblk0p9/uevent"
    touch "$FIXTURE/dev/mmcblk0p3" "$FIXTURE/dev/mmcblk0p8" "$FIXTURE/dev/mmcblk0p9"
fi
''');busy.chmod(0o755)
            code=function(name).replace('/sys/',str(root)+'/sys/').replace('/dev/',str(root)+'/dev/')
            code=code.replace('[ -b ','[ -f ').replace('/bin/busybox',str(busy))
            code='log() { echo "$*"; }\nmdev() { echo scan >> "$FIXTURE/scans"; }\nmisc=;bootb=;linux_slot='+slot+'\n'+code
            code+='\n'+name+(' 2' if name=='find_partitions' else '')+'\nresult=$?\nprintf "rc=%s misc=%s boot=%s\\n" "$result" "$misc" "$bootb"\n'
            import os
            r=subprocess.run(['sh','-c',code],env=dict(os.environ,FIXTURE=td,READY_AT=str(ready_at)),capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,0,r.stderr)
            ticks=int((root/'ticks').read_text())
            scans=(root/'scans').read_text().splitlines() if (root/'scans').exists() else []
            return r.stdout,ticks,scans

    def test_partition_ready_uses_linux_slot_and_returns_without_fixed_second(self):
        out,ticks,_=self.run_case('find_partitions',3)
        self.assertEqual(ticks,3);self.assertIn('rc=0',out);self.assertIn('boot=',out)
        self.assertTrue(out.strip().endswith('mmcblk0p8'))
        out,_,_=self.run_case('find_partitions',3,slot='b')
        self.assertTrue(out.strip().endswith('mmcblk0p9'))

    def test_partition_budget_and_mdev_frequency_are_preserved(self):
        out,ticks,scans=self.run_case('find_partitions')
        self.assertIn('rc=1',out);self.assertEqual(ticks,20);self.assertEqual(len(scans),2)

    def test_wcn_ready_and_full_timeout_keep_firmware_handoff_guard(self):
        out,ticks,_=self.run_case('early_wcn_ready',3)
        self.assertEqual(ticks,3);self.assertIn('wcn-handoff-ready waited_ms=600',out)
        out,ticks,_=self.run_case('early_wcn_ready')
        self.assertEqual(ticks,75);self.assertIn('wcn-handoff-timeout waited_ms=15000',out)


if __name__=='__main__':unittest.main()
