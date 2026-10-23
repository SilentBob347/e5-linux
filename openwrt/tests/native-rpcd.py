"""Load the production plugin in actual rpcd, with private read-only fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from native_dashboard_fixture import Snapshot, TOP


@unittest.skipUnless(Path('/tmp/event-test-ready').exists(),'isolated OpenWrt runtime required')
class Rpcd(unittest.TestCase):
    def test_real_plugin_methods_errors_and_repeated_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);s=Snapshot(root/'fixture')
            # Materialize deterministic files before rpcd imports the fixture.
            s.run()
            plugin=Path('/usr/share/rpcd/ucode/e5status-backport-test.uc')
            self.assertFalse(plugin.exists(),'refusing to replace an unrelated plugin')
            source=(TOP/'openwrt/luci-app-t551m/root/usr/share/rpcd/ucode/e5status.uc').read_text()
            plugin.write_text(source.replace("'e5.dash'",json.dumps(str(s.module/'dash.uc'))))
            sock=root/'ubus.sock'
            env=dict(os.environ,MU300_DASH_SYSROOT=str(s.root),MU300_DASH_CONFIG=str(s.config),
                     DASH_FIXTURE=str(s.root),DASH_FIXTURE_NOW=str(s.now))
            bus=subprocess.Popen(['/sbin/ubusd','-s',str(sock)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process=None
            try:
                for _ in range(100):
                    if sock.exists():break
                    time.sleep(.01)
                with (root/'rpcd.log').open('w+') as log:
                    process=subprocess.Popen(['/sbin/rpcd','-s',str(sock)],env=env,stdout=log,stderr=log)
                    def call(*args):
                        return subprocess.run(['/bin/ubus','-s',str(sock),*args],capture_output=True,text=True,timeout=8)
                    for _ in range(100):
                        if call('list','e5status').returncode==0:break
                        time.sleep(.02)
                    log.seek(0);self.assertEqual(call('list','e5status').returncode,0,log.read())
                    for _ in range(3):
                        r=call('call','e5status','sysinfo','{}')
                        self.assertEqual(r.returncode,0,r.stderr)
                        info=json.loads(r.stdout)
                        for key in ('cpu','power','wifi','wan','boot','traffic','conns'):self.assertIn(key,info)
                    self.assertIn('signature',json.loads(call('call','e5status','sms_head','{}').stdout))
                    self.assertIn('error',json.loads(call('call','e5status','rates','{"slot":"bad"}').stdout))
                    self.assertNotEqual(call('call','e5status','exec','{"command":"reboot"}').returncode,0)
                    self.assertIsNone(process.poll())
            finally:
                if process:process.terminate();process.wait(timeout=5)
                bus.terminate();bus.wait(timeout=5);plugin.unlink()


if __name__=='__main__':unittest.main()
