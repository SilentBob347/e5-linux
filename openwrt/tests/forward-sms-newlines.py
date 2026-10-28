#!/usr/bin/env python3
"""Real forwarding length guard; no modem, network or delivery."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

TOP = Path(__file__).resolve().parents[2]
SOURCE = TOP / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/sms-forward'


class Newlines(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX shells required')
    def test_actual_guard_counts_all_newlines(self):
        source = SOURCE.read_text()
        function = source[source.index('sms_units() {'):source.index('deliver() {')]
        shells = [[s] for s in ('bash', 'dash') if shutil.which(s)]
        if shutil.which('busybox'):
            shells.append(['busybox', 'ash'])
        self.assertTrue(shells)
        for shell in shells:
            for body in ('', 'a', '\n', 'a\n', 'a\n\n', '\r\n', '😀\n', 'a' * 69 + '\n\n', '\\n'):
                with self.subTest(shell=shell, body=repr(body)):
                    result = subprocess.run(shell + ['-c', function + '\nsms_units "$BODY"'],
                                            env=dict(os.environ, BODY=body), capture_output=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(int(result.stdout), len(body.encode('utf-16-be')) // 2)


if __name__ == '__main__':
    unittest.main()
