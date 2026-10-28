#!/usr/bin/env python3
"""Execute the deferred PHY-add/S92 hook, including concurrent notifications."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'overlay/usr/libexec/e5-first-wireless'


@unittest.skipUnless(sys.platform == 'linux', 'requires POSIX shell and flock')
class DeferredWireless(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.defaults = self.root / 'defaults'
        self.defaults.write_text('echo setup >> "$RESULT"\nsleep .2\nexit ${FAIL:-0}\n')
        self.phy = self.root / 'phy'
        self.phy.mkdir()
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        wifi = bin_dir / 'wifi'
        wifi.write_text('#!/bin/sh\necho "$*" >> "$RESULT"\n')
        wifi.chmod(0o755)
        self.result = self.root / 'result'
        self.env = dict(os.environ, RESULT=str(self.result), PATH=str(bin_dir)+':'+os.environ['PATH'])
        self.script = self.root / 'hook'
        self.script.write_text(SOURCE.read_text().replace('/etc/uci-defaults/91-e5-wireless', str(self.defaults))
            .replace('/var/lock/e5-first-wireless.lock', str(self.root/'lock'))
            .replace('/sys/class/ieee80211', str(self.phy)))

    def run_hook(self, **env):
        return subprocess.run(['sh', str(self.script)], env=dict(self.env, **env), capture_output=True)

    def test_missing_phy_is_not_successful_initialization(self):
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertTrue(self.defaults.exists())
        self.assertFalse(self.result.exists())

    def test_failed_setup_is_retained_and_can_retry(self):
        (self.phy/'phy0').mkdir()
        self.assertNotEqual(self.run_hook(FAIL='1').returncode, 0)
        self.assertTrue(self.defaults.exists())
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertFalse(self.defaults.exists())
        self.assertEqual(self.result.read_text().splitlines(), ['setup', 'setup', 'reload'])
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.result.read_text().splitlines(), ['setup', 'setup', 'reload'])

    def test_parallel_notifications_do_not_reconfigure_twice(self):
        (self.phy/'phy0').mkdir()
        jobs = [subprocess.Popen(['sh', str(self.script)], env=self.env) for _ in range(4)]
        for job in jobs:
            self.assertEqual(job.wait(timeout=5), 0)
        self.assertEqual(self.result.read_text().splitlines(), ['setup', 'reload'])


if __name__ == '__main__': unittest.main()
