#!/usr/bin/env python3
"""Real kernel lock ownership, legacy migration and process-death retries."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
SOURCE=(TOP/'openwrt/bundle/part-write.sh').read_text()
LOCK=SOURCE[SOURCE.index('guard=/data/local/tmp/'):SOURCE.index('mkdir "$stage/dev"')]


class InstallerLock(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        (self.root/'proc').mkdir();(self.root/'target').touch()

    def script(self,hold=False):
        code=LOCK.replace('/data/local/tmp/',str(self.root)+'/').replace('/proc/',str(self.root/'proc')+'/')
        return ('set -eu\nchroot() { shift; "$@"; }\n'+
                f'lock="{self.root}/e5-part-write.lock";dev="{self.root}/target";stage=unused\n'+code+
                ('echo READY\nexec sleep 60\n' if hold else 'rmdir "$lock"\n'))

    def run_lock(self):return subprocess.run(['busybox','ash'],input=self.script(),text=True,capture_output=True,timeout=5)

    def test_empty_legacy_lock_is_automatically_recovered(self):
        (self.root/'e5-part-write.lock').mkdir()
        result=self.run_lock();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Recovered stale',result.stdout)
        self.assertFalse((self.root/'e5-part-write.lock').exists())
        self.assertTrue((self.root/'e5-part-write.flock').is_file())
        self.assertEqual(self.run_lock().returncode,0)

    def test_real_holder_blocks_concurrency_and_sigkill_releases_for_retry(self):
        holder=subprocess.Popen(['busybox','ash'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            holder.stdin.write(self.script(hold=True));holder.stdin.close()
            self.assertEqual(holder.stdout.readline().strip(),'READY')
            blocked=self.run_lock();self.assertNotEqual(blocked.returncode,0)
            self.assertIn('actively writing',blocked.stderr)
            inode=(self.root/'e5-part-write.flock').stat().st_ino
            holder.kill();holder.wait(timeout=5)
            recovered=self.run_lock();self.assertEqual(recovered.returncode,0,recovered.stderr)
            self.assertEqual((self.root/'e5-part-write.flock').stat().st_ino,inode)
        finally:
            if holder.poll() is None:holder.kill();holder.wait()
            holder.stdout.close();holder.stderr.close()

    def test_old_live_script_is_not_mistaken_for_stale_directory(self):
        (self.root/'e5-part-write.lock').mkdir()
        task=self.root/'proc/12345';task.mkdir()
        (task/'cmdline').write_bytes(b'/data/local/tmp/busybox\0sh\0/data/local/tmp/e5-part-write.sh\0')
        result=self.run_lock();self.assertNotEqual(result.returncode,0)
        self.assertIn('older installation is still running',result.stderr)
        self.assertTrue((self.root/'e5-part-write.lock').exists())

    def test_unknown_contents_and_symlink_are_never_deleted(self):
        lock=self.root/'e5-part-write.lock';lock.mkdir();(lock/'user-file').write_text('keep')
        result=self.run_lock();self.assertNotEqual(result.returncode,0)
        self.assertEqual((lock/'user-file').read_text(),'keep')
        (lock/'user-file').unlink();lock.rmdir();lock.symlink_to(self.root/'proc',target_is_directory=True)
        self.assertNotEqual(self.run_lock().returncode,0);self.assertTrue(lock.is_symlink())


if __name__=='__main__':unittest.main()
