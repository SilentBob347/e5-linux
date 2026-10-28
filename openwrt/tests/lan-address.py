#!/usr/bin/env python3
"""Run legacy LAN migration and USB handoff without touching host networking."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

OVERLAY = Path(__file__).resolve().parents[1] / 'overlay'
MOCK = r'''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['LAN_FIXTURE'])
s = json.loads(p.read_text()); args = sys.argv[1:]
if Path(sys.argv[0]).name == 'uci':
 if args[0] == '-q': args = args[1:]
 op = args[0]
 if op == 'get':
  if args[1] == 'network.lan.proto': print(s['proto'])
  else: print(' '.join(s['addresses']))
 elif op == 'del_list':
  if s.get('fail') == 'delete': sys.exit(1)
  s['addresses'].remove(args[1].split('=', 1)[1])
 elif op == 'commit':
  if s.get('fail') == 'commit': sys.exit(1)
  s['commits'] += 1
 else: sys.exit(2)
else:
 s['ip_calls'].append(args)
 if args == ['-4', '-o', 'addr', 'show', 'dev', 'br-lan', 'scope', 'global']:
  if s['ready']: print('2: br-lan inet 192.168.88.1/24 scope global br-lan')
 elif args == ['-4', 'addr', 'flush', 'dev', 'usb0']: s['usb_addresses'] = []
p.write_text(json.dumps(s))
'''


@unittest.skipUnless(sys.platform == 'linux', 'Linux shell fixture')
class LanAddress(unittest.TestCase):
    def run_script(self, name, addresses=(), *, stamp=True, proto='static',
                   action='ifup', interface='lan', ready=True, fail=None, shell=('sh',)):
        with tempfile.TemporaryDirectory(prefix='e5-lan-') as temp:
            root = Path(temp)
            for directory in ('bin', 'etc/e5', 'net/usb0', 'net/br-lan/brif', 'proc/usb0'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            if stamp: (root / 'etc/e5/configured.network').touch()
            (root / 'proc/usb0/disable_ipv6').touch()
            state = root / 'state.json'
            state.write_text(json.dumps(dict(addresses=list(addresses), proto=proto,
                ready=ready, commits=0, ip_calls=[], usb_addresses=['192.168.77.1/24'], fail=fail)))
            for command in ('uci', 'ip'):
                p = root / 'bin' / command
                p.write_text(MOCK); p.chmod(0o755)
            p = root / 'bin/logger'; p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
            source = (OVERLAY / name).read_text().replace('/etc/e5', str(root / 'etc/e5'))
            source = source.replace('/sys/class/net', str(root / 'net'))
            source = source.replace('/proc/sys/net/ipv6/conf', str(root / 'proc'))
            # BusyBox may resolve its built-in ip before PATH; always use stubs.
            source = 'ip() { "$TEST_BIN/ip" "$@"; }\nuci() { "$TEST_BIN/uci" "$@"; }\n' + source
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                       TEST_BIN=str(root / 'bin'), LAN_FIXTURE=str(state), ACTION=action, INTERFACE=interface)
            result = subprocess.run([*shell, '-c', source], env=env, capture_output=True, text=True)
            return result, json.loads(state.read_text())

    def test_legacy_alias_removed_with_default_or_changed_primary(self):
        for primary in ('192.168.9.1/24', '192.168.88.1/24'):
            r, s = self.run_script('etc/uci-defaults/98-e5-lan-address',
                (primary, '192.168.77.1/24', '10.1.2.1/24'))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(s['addresses'], [primary, '10.1.2.1/24'])
            self.assertEqual(s['commits'], 1)

    def test_single_and_custom_addresses_preserved(self):
        for values, stamp, proto in (
                (['192.168.77.1/24'], True, 'static'),
                (['192.168.88.1/24', '10.1.2.1/24'], True, 'static'),
                (['192.168.9.1/24', '192.168.77.1/24'], False, 'static'),
                (['192.168.9.1/24', '192.168.77.1/24'], True, 'dhcp')):
            r, s = self.run_script('etc/uci-defaults/98-e5-lan-address', values, stamp=stamp, proto=proto)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(s['addresses'], values)
            self.assertEqual(s['commits'], 0)

    def test_migration_failures_retain_boot_retry(self):
        for fail in ('delete', 'commit'):
            r, _ = self.run_script('etc/uci-defaults/98-e5-lan-address',
                ('192.168.9.1/24', '192.168.77.1/24'), fail=fail)
            self.assertNotEqual(r.returncode, 0)

    def test_handoff_on_start_and_address_change(self):
        shells = [('sh',)] + ([('busybox', 'sh')] if shutil.which('busybox') else [])
        for shell in shells:
            for action in ('ifup', 'ifupdate'):
                r, s = self.run_script('etc/hotplug.d/iface/10-e5-usb0', action=action, shell=shell)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(s['usb_addresses'], [])
                self.assertFalse(any('down' in call or '-6' in call for call in s['ip_calls']))

    def test_no_cleanup_before_lan_ready_or_on_other_events(self):
        for options in (dict(ready=False), dict(action='ifdown'), dict(interface='wan')):
            r, s = self.run_script('etc/hotplug.d/iface/10-e5-usb0', **options)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(s['usb_addresses'], ['192.168.77.1/24'])

    def test_new_defaults_have_no_rescue_alias(self):
        source = (OVERLAY / 'etc/uci-defaults/90-e5').read_text()
        self.assertNotIn("add_list network.lan.ipaddr='192.168.77.1/24'", source)


if __name__ == '__main__':
    unittest.main()
