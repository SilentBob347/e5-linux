#!/usr/bin/env python3
"""Exercise optional metrics: deadlines, unknown values and cache isolation."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/wifi-station-metrics'
spec = importlib.util.spec_from_loader('metrics', importlib.machinery.SourceFileLoader('metrics', str(FILE)))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
MAC = '00:11:22:33:44:55'


class Metrics(unittest.TestCase):
    def test_unknown_and_wrong_station(self):
        self.assertEqual(m.normalize([MAC, '0', '0 Mbit/s', '', '']), [MAC, '', '', '', ''])
        self.assertIsNone(m.normalize(['invalid', '-40', '', '', '']))
        self.assertIsNone(m.parse_get('Station ff:ff:ff:ff:ff:ff\n signal: -30', MAC))
        result = m.parse_get('Station ' + MAC + '\n\tsignal: -55 [-55, -57] dBm\n\ttx bitrate: 433.3 MBit/s VHT-MCS 9\n\trx bitrate: 86.7 MBit/s', MAC)
        self.assertEqual(result, [MAC, '-55', '433.3 Mbit/s', '86.7 Mbit/s', ''])

    def test_cache_never_adds_clients_or_overrides_fresh_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            index = Path('/sys/class/net/lo/ifindex').read_text().strip()
            path = cache / ('lo-' + index + '.json')
            path.write_text(json.dumps({'ts': time.monotonic(), 'values': {
                MAC: [MAC, '-55', '433 Mbit/s', '86 Mbit/s', ''],
                '00:11:22:33:44:99': ['00:11:22:33:44:99', '-40', '', '', '']}}))
            with patch.object(m.subprocess, 'Popen') as spawn:
                result = m.fill([[MAC, '-42', '', '', '1 min']], 'lo', cache)
                self.assertEqual(result, [[MAC, '-42', '433 Mbit/s', '86 Mbit/s', '1 min']])
                self.assertEqual(m.fill([], 'lo', cache), [])
                spawn.assert_not_called()
            path.write_text(json.dumps({'ts': time.monotonic(), 'values': {}}))
            with patch.object(m.subprocess, 'Popen') as spawn:
                self.assertEqual(m.fill([[MAC, '', '', '', '']], 'lo', cache), [[MAC, '', '', '', '']])
                spawn.assert_not_called()  # Failed probes are throttled too.

    def test_worker_deadline_and_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            iw = cache / 'iw'
            iw.write_text('#!/usr/bin/python3\nimport time\ntime.sleep(2)\n')
            iw.chmod(0o755)
            clients = ['00:11:22:33:44:%02x' % n for n in range(12)]
            with patch.dict(os.environ, PATH=temp + ':' + os.environ['PATH']):
                start = time.monotonic()
                m.refresh('lo', 'lo-1', clients, cache)
                self.assertLess(time.monotonic() - start, 1.4)
            data = json.loads((cache / 'lo-1.json').read_text())
            self.assertEqual(data['values'], {})
            self.assertGreater(data['cursor'], 0)
            self.assertLess(data['cursor'], len(clients))

    def test_no_overlapping_worker_and_immediate_return(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            index = Path('/sys/class/net/lo/ifindex').read_text().strip()
            lock = cache / ('lo-' + index + '.lock')
            with lock.open('w') as holder:
                fcntl.flock(holder, fcntl.LOCK_EX)
                with patch.object(m.subprocess, 'Popen') as spawn:
                    start = time.monotonic()
                    self.assertEqual(m.fill([[MAC, '', '', '', '']], 'lo', cache), [[MAC, '', '', '', '']])
                    self.assertLess(time.monotonic() - start, 0.1)
                    spawn.assert_not_called()

    def test_real_background_worker_and_inherited_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / 'cache'
            cache.mkdir(mode=0o700)
            helper = root / 'helper.py'
            helper.write_text(FILE.read_text().replace("Path('/run/unisoc-wifi-metrics')", 'Path(' + repr(str(cache)) + ')'))
            spec = importlib.util.spec_from_file_location('worker_fixture', helper)
            worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(worker)
            gate = root / 'gate'
            os.mkfifo(gate)
            gatefd = os.open(gate, os.O_RDWR | os.O_NONBLOCK)
            self.addCleanup(os.close, gatefd)
            iw = root / 'iw'
            # Synchronize the overlap explicitly. Python interpreter startup
            # under emulation must not consume the real 300ms query budget.
            import shlex
            iw.write_text('#!/bin/sh\nread -r release < ' + shlex.quote(str(gate)) + '\n'
                          'printf "Station %s\\n\\tsignal: -54 dBm\\n\\ttx bitrate: 433.3 MBit/s\\n\\trx bitrate: 86.7 MBit/s\\n" "$5"\n'
                          'echo query >> ' + shlex.quote(str(root / 'queries')) + '\n')
            iw.chmod(0o755)
            row = [MAC, '', '', '', '']
            children = []
            original_spawn = worker.subprocess.Popen
            def spawn(*args, **kwargs):
                child = original_spawn(*args, **kwargs)
                children.append(child)
                return child
            with patch.dict(os.environ, PATH=temp + ':' + os.environ['PATH']), patch.object(worker.subprocess, 'Popen', side_effect=spawn):
                start = time.monotonic()
                self.assertEqual(worker.fill([row], 'lo'), [row])
                self.assertEqual(worker.fill([row], 'lo'), [row])
                self.assertLess(time.monotonic() - start, 0.15)
                self.assertEqual(len(children), 1)
                os.write(gatefd, b'continue\n')
                deadline = time.monotonic() + 3
                while not list(cache.glob('*.json')) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertEqual(worker.fill([row], 'lo'), [[MAC, '-54', '433.3 Mbit/s', '86.7 Mbit/s', '']])
            for child in children:
                self.assertEqual(child.wait(timeout=3), 0)
            self.assertEqual((root / 'queries').read_text(), 'query\n')

    def test_actual_station_dump_parser(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'openwrt/tests'))
        from native_dashboard_fixture import Snapshot
        with tempfile.TemporaryDirectory() as td:
            snap=Snapshot(Path(td))
            snap.stations=[
                {'mac':MAC,'sta_info':{'signal':0,'tx_bitrate':{'bitrate':4333}}},
                {'mac':'00:11:22:33:44:66','sta_info':{'signal':-61,'rx_bitrate':{'bitrate':867},'connected_time':123}},
                {'mac':'invalid','sta_info':{'signal':-30}}]
            result=snap.run()['wifi']
            self.assertEqual(result['clients_n'],2)
            self.assertIsNone(result['clients'][0]['signal'])
            self.assertEqual(result['clients'][0]['tx'],'433.3 Mbit/s')
            self.assertEqual(result['clients'][1]['signal'],-61)
            self.assertEqual(result['clients'][1]['rx'],'86.7 Mbit/s')
            self.assertEqual(result['clients'][1]['conn'],'2 min')


if __name__ == '__main__':
    unittest.main()
