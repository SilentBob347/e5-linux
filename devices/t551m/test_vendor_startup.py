"""Exercise the real boot gates with harmless fixture commands; no device I/O."""
from pathlib import Path
import os
import runpy
import shlex
import subprocess
import tempfile
import socket
import threading
import time
import unittest

TOP=Path(__file__).resolve().parents[2]
network=runpy.run_path(str(TOP/'devices/t551m/network-startup.py'))
patch=network['patch_vendor_startup']


class VendorBoot(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.service=self.root/'etc/init.d/e5-vendor'
        self.service.parent.mkdir(parents=True)
        self.original='''START=20
start_service() {
    printf 'nv-verified\\n' >> "$EVENTS"
    [ "${NV_FAIL:-0}" != 1 ] || return 1
    printf 'vendor-started\\n' >> "$EVENTS"
}
start() { start_service; }
'''
        self.service.write_text(self.original)
        self.events=self.root/'events';self.marker=self.root/'deferred'
        self.policy=self.root/'policy'
        self.policy.write_text('printf "%s\\n" "$POLICY"; exit "${POLICY_FAIL:-0}"\n')
        patch(self.root)

    def shell(self,code,**env):
        code=code.replace('/run/e5-vendor-deferred',str(self.marker))
        code=code.replace('/usr/bin/python3 /usr/libexec/e5-charge-mode --radio-boot-policy',f'sh {self.policy}')
        code=code.replace('/usr/bin/python3 /usr/libexec/e5-charge-mode','printf "charge-gate-complete\\n" >> "$EVENTS"')
        code=code.replace('/etc/init.d/e5-vendor start','start')
        return subprocess.run(['busybox','sh','-c',code],env=dict(os.environ,EVENTS=str(self.events),POLICY='early')|env,capture_output=True,text=True)

    def boot(self,**env):
        return self.shell(self.service.read_text()+'\nboot\n',**env)

    def test_normal_boot_starts_nv_and_cp_at_s09_and_is_idempotent(self):
        before=self.service.read_bytes();patch(self.root)
        self.assertEqual(before,self.service.read_bytes())
        self.assertTrue((self.root/'etc/rc.d/S09e5-vendor').is_symlink())
        self.assertFalse((self.root/'etc/rc.d/S20e5-vendor').exists())
        result=self.boot();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.events.read_text().splitlines(),['nv-verified','vendor-started'])
        self.assertFalse(self.marker.exists())

    def test_every_shared_update_profile_migrates_the_same_boot_gate(self):
        for profile in ('e5','t551m','m8','t512n','yuanhang41s','k1'):
            self.service.write_text(self.original)
            network['patch_root'](self.root,profile)
            self.assertIn('START=09',self.service.read_text())
            self.assertIn('nv-verified',self.service.read_text())
            self.assertEqual(self.boot().returncode,0)

    def test_charge_boot_does_not_prepare_nv_or_start_cp_until_gate_returns(self):
        result=self.boot(POLICY='defer');self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.events.exists());self.assertTrue(self.marker.exists())
        gate=(TOP/'devices/t551m/charge-mode-service').read_text()
        # Define start() from the patched service, then the real S14 boot gate.
        result=self.shell(self.service.read_text()+'\n'+gate+'\nboot\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.events.read_text().splitlines(),['charge-gate-complete','nv-verified','vendor-started'])
        self.assertFalse(self.marker.exists())

    def test_policy_failure_defers_radio_and_nv_failure_never_starts_cp(self):
        result=self.boot(POLICY_FAIL='1');self.assertNotEqual(result.returncode,0)
        self.assertTrue(self.marker.exists());self.assertFalse(self.events.exists())
        result=self.boot(NV_FAIL='1');self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.events.read_text().splitlines(),['nv-verified'])

    def test_foreign_start_link_is_rejected_before_mutation(self):
        link=self.root/'etc/rc.d/S20e5-vendor';link.symlink_to('../init.d/foreign')
        before=self.service.read_bytes()
        with self.assertRaisesRegex(ValueError,'Foreign'):patch(self.root)
        self.assertEqual(self.service.read_bytes(),before)
        self.assertEqual(link.readlink().as_posix(),'../init.d/foreign')

    def test_installed_guarded_vendor_script_migrates_without_losing_guards(self):
        vendor=self.root/'opt/e5/vendor-start.sh';vendor.parent.mkdir(parents=True)
        vendor.write_text('''#!/bin/sh
for u in /sys/class/block/mmcblk0p*/uevent; do
  d=$(basename "$(dirname "$u")"); n=$(sed -n 's/^PARTNAME=//p' "$u")
  case "$n" in nr_fixnv*|nr_runtimenv*|nr_deltanv*|calinv) continue ;; esac
  ln -sfn "/dev/$d" "/dev/block/$d"
done
  sleep 1
# per-model slot and bootconfig setup remains before the ready marker
touch /run/e5-vendor-prepared
echo "stage=exec"
''')
        patch(self.root);before=vendor.read_bytes();patch(self.root)
        self.assertEqual(vendor.read_bytes(),before)
        body=vendor.read_text()
        self.assertIn('nr_fixnv*|nr_runtimenv*|nr_deltanv*|calinv',body)
        self.assertIn('slot and bootconfig setup',body)
        self.assertLess(body.index('until [ -S'),body.index('touch /run/e5-vendor-prepared'))
        self.assertNotIn('  sleep 1\n',body)
        subprocess.run(['busybox','sh','-n',str(vendor)],check=True)

    def test_log_socket_wait_ends_at_readiness_and_rejects_missing_socket(self):
        endpoint=self.root/'logdw'
        code=network['VENDOR_LOG_WAIT'].replace('/dev/socket/logdw',str(endpoint)).replace('/opt/e5/bin/busybox','busybox')
        listener=socket.socket(socket.AF_UNIX);self.addCleanup(listener.close)
        def bind():time.sleep(.05);listener.bind(str(endpoint))
        thread=threading.Thread(target=bind);thread.start()
        before=time.monotonic();result=self.shell(code);thread.join()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(time.monotonic()-before,.5)
        endpoint.unlink()
        result=self.shell(code)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Android log socket unavailable',result.stderr)

    def test_cp_diskserver_gate_waits_instead_of_exhausting_invalid_sleep(self):
        self.service.write_text(self.original+"\ninstance cp_diskserver /bin/sh -c 'i=0; until [ -e /run/e5-vendor-prepared ]; do i=$((i + 1)); [ $i -lt 120 ] || exit 1; sleep 0.1; done; exec /opt/e5/android-run cp_diskserver'\n")
        patch(self.root)
        line=next(l for l in self.service.read_text().splitlines() if l.startswith('instance cp_diskserver'))
        code=shlex.split(line)[-1]
        ready=self.root/'vendor-prepared';started=self.root/'cp-started'
        daemon=self.root/'android-run';daemon.write_text('printf "%s" "$1" > '+str(started)+'\n')
        code=code.replace('/run/e5-vendor-prepared',str(ready)).replace('/opt/e5/bin/busybox','busybox').replace('/opt/e5/android-run','busybox sh '+str(daemon))
        before=time.monotonic();process=subprocess.Popen(['busybox','sh','-c',code],stderr=subprocess.PIPE)
        try:
            time.sleep(.25)
            self.assertIsNone(process.poll(),'gate exited before preparation completed')
            self.assertFalse(started.exists())
            ready.touch()
            _,err=process.communicate(timeout=2)
            self.assertEqual(process.returncode,0,err)
            self.assertEqual(started.read_text(),'cp_diskserver')
            self.assertLess(time.monotonic()-before,1)
        finally:
            if process.poll() is None:process.kill();process.wait()


if __name__=='__main__':unittest.main()
