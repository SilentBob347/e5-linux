"""Real native socket/PTY tests. A private sysroot replaces every device path."""
import json
import os
from pathlib import Path
import pty
import select
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import tty
import unittest


class NativeOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build=tempfile.TemporaryDirectory(prefix='e5-at-build-')
        cls.binary=Path(os.environ.get('E5_TEST_AT_OWNER',str(Path(cls.build.name)/'atd')))
        if 'E5_TEST_AT_OWNER' not in os.environ:
            subprocess.run(['cc','-std=c11','-Os','-Wall','-Wextra','-Werror',
                str(Path(__file__).with_name('atd.c')),'-o',str(cls.binary)],check=True)

    @classmethod
    def tearDownClass(cls):cls.build.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='eat-');self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for p in ('run','dev','sys/class/wwan/wwan0at0','sys/module/sipc_wwan/parameters'):
            (self.root/p).mkdir(parents=True,exist_ok=True)
        for key,value in [('cmd_ring','1'),('urc_ring','0'),('drain_rings','3,4,5'),('card','0')]:
            (self.root/'sys/module/sipc_wwan/parameters'/key).write_text(value+'\n')
        self.master,self.slave=pty.openpty();tty.setraw(self.slave)
        self.addCleanup(os.close,self.master);self.addCleanup(os.close,self.slave)
        for nr in (2,6,7):(self.root/f'dev/stty_nr{nr}').symlink_to(os.ttyname(self.slave))
        self.process=self.spawn()
        self.endpoint=self.root/'run/t551m-at2/cmd.sock'
        deadline=time.monotonic()+5
        while not self.endpoint.exists() and time.monotonic()<deadline:
            self.assertIsNone(self.process.poll(),self.output(self.process));time.sleep(.01)
        self.assertTrue(self.endpoint.exists())

    def spawn(self,nr=2):
        p=subprocess.Popen([str(self.binary),'--serve','--channel',str(nr)],
            env=dict(os.environ,E5_AT_ROOT=str(self.root)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def cleanup():
            if p.poll() is None:p.terminate()
            try:p.communicate(timeout=4)
            except subprocess.TimeoutExpired:p.kill();p.communicate()
        self.addCleanup(cleanup)
        return p

    def output(self,p):
        return p.communicate()[1].decode() if p.poll() is not None else ''

    def submit(self,command='AT+CSQ',**fields):
        request=dict(command=command,timeout=1,deadline=time.monotonic()+12,**fields)
        return self.raw(json.dumps(request).encode()+b'\n')

    def raw(self,data):
        client=socket.socket(socket.AF_UNIX);client.settimeout(10);client.connect(str(self.endpoint));client.sendall(data)
        self.addCleanup(client.close);return client

    def result(self,client):
        data=b''
        while True:
            chunk=client.recv(16384)
            if not chunk:break
            data+=chunk
        client.close();return json.loads(data)

    def sent(self,expected):
        self.assertTrue(select.select([self.master],[],[],4)[0],'no AT bytes')
        data=os.read(self.master,4096);self.assertEqual(data,expected)

    def quiet(self):self.assertFalse(select.select([self.master],[],[],.05)[0],'unexpected AT write')

    def test_normal_commands_have_50ms_minimum_send_gap(self):
        times=[]
        for _ in range(4):
            c=self.submit('AT')
            self.sent(b'AT\r')
            times.append(time.monotonic())
            os.write(self.master,b'OK\r\n')
            self.assertTrue(self.result(c)['ok'])
        for previous,current in zip(times,times[1:]):
            gap=current-previous
            self.assertGreaterEqual(gap,.045)
            self.assertLess(gap,.095)

    def test_fragmented_reply_and_plain_contract(self):
        c=self.submit();self.sent(b'AT+SPACTCARD=0;+CSQ\r')
        os.write(self.master,b'+CS');time.sleep(.01);os.write(self.master,b'Q: 20,99\r\nO');time.sleep(.01);os.write(self.master,b'K\r\n')
        self.assertEqual(self.result(c),{'ok':True,'response':'+CSQ: 20,99\nOK\n'})
        c=self.submit(plain=True);self.sent(b'AT+SPACTCARD=0;+CSQ\r');os.write(self.master,b'OK\r\n')
        self.assertEqual(c.recv(1024),b'0\nOK\n');c.close()

    def test_success_does_not_pay_initial_drain_again(self):
        start=time.monotonic();c=self.submit('AT');self.sent(b'AT\r');os.write(self.master,b'OK\n')
        self.assertTrue(self.result(c)['ok']);self.assertLess(time.monotonic()-start,.4)

    def test_error_final_is_complete_and_card_is_per_command(self):
        (self.root/'sys/module/sipc_wwan/parameters/card').write_text('1\n')
        c=self.submit('AT+CPIN?');self.sent(b'AT+SPACTCARD=1;+CPIN?\r');os.write(self.master,b'+CME ERROR: 10\r\n')
        self.assertIn('ERROR: 10',self.result(c)['response'])
        c=self.submit('AT+SPACTCARD=0;+CIMI');self.sent(b'AT+SPACTCARD=0;+CIMI\r');os.write(self.master,b'OK\n')
        self.assertTrue(self.result(c)['ok'])

    def test_timeout_quarantine_and_late_final(self):
        c=self.submit('AT+SET=1');self.sent(b'AT+SPACTCARD=0;+SET=1\r');self.assertFalse(self.result(c)['ok'])
        c=self.submit('AT+NEXT?');self.assertFalse(self.result(c)['ok']);self.quiet()
        os.write(self.master,b'+SET: late\r\nOK\r\n');time.sleep(.03)
        c=self.submit('AT+NEXT?');self.sent(b'AT+SPACTCARD=0;+NEXT?\r');os.write(self.master,b'+NEXT: new\nOK\n')
        r=self.result(c);self.assertTrue(r['ok']);self.assertNotIn('late',r['response'])

    def test_recovery_requires_named_replies_and_does_not_repeat_setter(self):
        c=self.submit('AT+SET=1');self.sent(b'AT+SPACTCARD=0;+SET=1\r');self.assertFalse(self.result(c)['ok'])
        time.sleep(2.05)
        c=self.submit('AT+NEXT?');self.sent(b'AT+CFUN?\r');os.write(self.master,b'OK\n+OLD: late\n+CFUN: 1\nOK\n')
        self.sent(b'AT+CSQ\r');os.write(self.master,b'OK\n+CSQ: 20,99\nOK\n')
        self.sent(b'AT+SPACTCARD=0;+NEXT?\r');os.write(self.master,b'OK\n');self.assertTrue(self.result(c)['ok'])

    def test_recovery_bare_ok_does_not_unlock(self):
        c=self.submit('AT+SET=1');self.sent(b'AT+SPACTCARD=0;+SET=1\r');self.assertFalse(self.result(c)['ok'])
        time.sleep(2.05)
        c=self.submit('AT+NEXT?');self.sent(b'AT+CFUN?\r');os.write(self.master,b'OK\n')
        self.assertFalse(self.result(c)['ok']);self.quiet();self.assertIsNone(self.process.poll())

    def test_rejected_recovery_does_not_close_or_reopen_descriptor(self):
        c=self.submit('AT+SET=1');self.sent(b'AT+SPACTCARD=0;+SET=1\r');self.assertFalse(self.result(c)['ok'])
        time.sleep(2.05)
        c=self.submit('AT+NEXT?');self.sent(b'AT+CFUN?\r');os.write(self.master,b'+CFUN: 1\nERROR\n')
        self.assertFalse(self.result(c)['ok']);self.quiet();self.assertIsNone(self.process.poll())

    def test_independent_collector_channel_is_not_blocked(self):
        master,slave=pty.openpty();tty.setraw(slave)
        self.addCleanup(os.close,master);self.addCleanup(os.close,slave)
        device=self.root/'dev/stty_nr6';device.unlink();device.symlink_to(os.ttyname(slave))
        process=self.spawn(6);endpoint=self.root/'run/t551m-at6/cmd.sock'
        until=time.monotonic()+4
        while not endpoint.exists() and time.monotonic()<until:
            self.assertIsNone(process.poll());time.sleep(.01)
        slow=self.submit('AT+SLOW?');self.sent(b'AT+SPACTCARD=0;+SLOW?\r')
        fast=socket.socket(socket.AF_UNIX);self.addCleanup(fast.close);fast.settimeout(2);fast.connect(str(endpoint))
        start=time.monotonic();fast.sendall(json.dumps(dict(command='AT',timeout=1,deadline=start+12)).encode()+b'\n')
        self.assertTrue(select.select([master],[],[],1)[0]);self.assertEqual(os.read(master,1024),b'AT\r')
        os.write(master,b'OK\n');self.assertTrue(self.result(fast)['ok'])
        self.assertLess(time.monotonic()-start,.4);self.assertFalse(self.result(slow)['ok'])

    def test_expired_and_disconnected_queued_write_are_discarded(self):
        first=self.submit('AT+SLOW?');self.sent(b'AT+SPACTCARD=0;+SLOW?\r')
        queued=self.raw(json.dumps(dict(command='AT+WRITE=1',timeout=1,deadline=time.monotonic()+.1)).encode()+b'\n')
        dead=self.submit('AT+WRITE=2');dead.close()
        self.assertFalse(self.result(first)['ok']);self.assertFalse(self.result(queued)['ok']);time.sleep(.03);self.quiet()

    def test_malformed_ascii_control_and_expired_requests_never_write(self):
        invalid=[b'[]\n',b'{"command":"AT\\u"}\n',b'{"command":"AT","x":{"a":[]},"deadline":0}\n']
        for raw in invalid:self.assertFalse(self.result(self.raw(raw))['ok'])
        for command in ('AT\rAT+CFUN=0','AT\x00BAD','hello'):
            self.assertFalse(self.result(self.submit(command))['ok'])
        self.quiet();self.assertIsNone(self.process.poll())

    def test_single_owner_and_generation_change(self):
        duplicate=self.spawn();self.assertNotEqual(duplicate.wait(timeout=3),0)
        port=self.root/'sys/class/wwan/wwan0at0'
        renamed=port.with_name('old-port');port.rename(renamed);port.mkdir()
        self.assertNotEqual(self.process.wait(timeout=3),0)

    def test_unrelated_wwan_event_and_idle_do_not_reopen_or_poll(self):
        (self.root/'sys/class/wwan/other').mkdir();time.sleep(.03);self.assertIsNone(self.process.poll())
        def ticks():return sum(int(v) for v in Path(f'/proc/{self.process.pid}/stat').read_text().split()[13:15])
        before=ticks();time.sleep(.3);self.assertLessEqual(ticks()-before,1)
        self.quiet()

    def test_other_reserved_rings_cannot_be_opened(self):
        (self.root/'sys/module/sipc_wwan/parameters/drain_rings').write_text('3,6\n')
        p=self.spawn(6);self.assertNotEqual(p.wait(timeout=3),0)
        self.assertFalse((self.root/'run/t551m-at6/cmd.sock').exists())

    def test_invalid_ownership_metadata_fails_before_opening_another_ring(self):
        (self.root/'sys/module/sipc_wwan/parameters/cmd_ring').write_text('unknown\n')
        p=self.spawn(6);self.assertNotEqual(p.wait(timeout=3),0)
        self.assertFalse((self.root/'run/t551m-at6/cmd.sock').exists())

    def test_explicit_disabled_urc_ring_is_valid(self):
        (self.root/'sys/module/sipc_wwan/parameters/urc_ring').write_text('-1\n')
        p=self.spawn(6);endpoint=self.root/'run/t551m-at6/cmd.sock'
        until=time.monotonic()+4
        while not endpoint.exists() and time.monotonic()<until:
            self.assertIsNone(p.poll(),self.output(p));time.sleep(.01)
        self.assertTrue(endpoint.exists())

    def test_bad_utf8_is_replaced_without_losing_final_framing(self):
        c=self.submit('AT+CGMI');self.sent(b'AT+SPACTCARD=0;+CGMI\r')
        os.write(self.master,b'Vendor \xff\nOK\n')
        self.assertEqual(self.result(c),{'ok':True,'response':'Vendor \ufffd\nOK\n'})

    @unittest.skipIf('E5_TEST_AT_OWNER' in os.environ,'host client compiler test runs in host suite')
    def test_existing_native_client_talks_to_real_owner(self):
        client=self.root/'client'
        subprocess.run(['cc','-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-DAT_SOCKET_PREFIX='+json.dumps(str(self.root/'run/t551m-at')),
            str(Path(__file__).with_name('at-client.c')),'-o',str(client)],check=True)
        p=subprocess.Popen([str(client),'-t','1','AT+CSQ'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda: p.kill() if p.poll() is None else None)
        self.sent(b'AT+SPACTCARD=0;+CSQ\r');os.write(self.master,b'+CSQ: 20,99\nOK\n')
        out,err=p.communicate(timeout=3)
        self.assertEqual(p.returncode,0,err);self.assertEqual(out,b'+CSQ: 20,99\nOK\n')


if __name__=='__main__':unittest.main()
