"""Production C regressions. Fake ALSA, private D-Bus, loopback HTTP and files only."""
import copy
import ctypes
import http.server
import importlib.util
import json
import os
from pathlib import Path
import random
import runpy
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

HERE=Path(__file__).resolve().parent/'infoscreen/native'
TOP=HERE.parents[3]
support=runpy.run_path(str(HERE/'test-support.py'))


def wait(check, timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError, ValueError, KeyError):pass
        time.sleep(.03)
    raise AssertionError('Timed out waiting for expected native state')


def recv_exact(sock,n):
    data=b''
    while len(data)<n:
        block=sock.recv(n-len(data))
        if not block:raise EOFError('WebSocket disconnected')
        data+=block
    return data


def frame(sock,payload,opcode=1,final=True):
    if isinstance(payload,str):payload=payload.encode()
    size=len(payload);head=bytes([(128 if final else 0)|opcode,128|size]) if size<126 else bytes([(128 if final else 0)|opcode,254])+struct.pack('!H',size)
    mask=b'abcd';sock.sendall(head+mask+bytes(c^mask[i%4] for i,c in enumerate(payload)))


def receive(sock):
    a,b=recv_exact(sock,2);n=b&127
    if n==126:n=struct.unpack('!H',recv_exact(sock,2))[0]
    if n==127:n=struct.unpack('!Q',recv_exact(sock,8))[0]
    return a&15,recv_exact(sock,n)


class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        build=support['compile_native']
        cls.voice=build(cls.root,'voice',[HERE/n for n in ('voice.c','voice-hardware.c','screen-http.c','native-common.c')])
        cls.sim=build(cls.root,'sim-test',[HERE/'test-sim.c',HERE/'native-common.c'])
        cls.bt=build(cls.root,'voice-test',[HERE/n for n in ('test-voice.c','voice-hardware.c','screen-http.c','native-common.c')])
        cls.hw=build(cls.root,'hardware-test',[HERE/'test-hardware.c',HERE/'native-common.c'])
        cls.lib=ctypes.CDLL(str(build(cls.root,'audio.so',[HERE/'voice-hardware.c',HERE/'native-common.c'],['-shared','-fPIC'])))
        cls.lib.audio_profile_adjust.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_void_p]
        cls.lib.audio_profile_adjust.restype=ctypes.c_bool
        cls.lib.audio_profile_word.argtypes=[ctypes.c_uint,ctypes.c_bool,ctypes.c_bool]
        cls.lib.audio_profile_word.restype=ctypes.c_uint
        directory=cls.root/'usr/share/e5';directory.mkdir(parents=True)
        directory.joinpath('voice-routes.json').write_bytes(runpy.run_path(str(TOP/'devices/common/build-screen-native.py'))['route_manifest']())

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_recipient_profile_byte_parity(self):
        reference=runpy.run_path(str(TOP/'rootfs/overlay/opt/e5/e5_call_profiles.py'))['quieter_low_steps']
        rand=random.Random(1023)
        for sample in range(8):
            raw=bytearray(struct.pack('<16sII',b'audio_profile',40,0x2da)+rand.randbytes(40*0x2da))
            for mode in range(40):struct.pack_into('<7H',raw,24+mode*0x2da+0x244,*[rand.randrange(1,65536) for _ in range(7)])
            for attenuation in (0,1,12,24,36):
                buf=ctypes.create_string_buffer(bytes(raw),len(raw))
                self.assertTrue(self.lib.audio_profile_adjust(buf,len(raw),attenuation,None))
                self.assertEqual(buf.raw,reference(bytes(raw),attenuation))
        for raw,attenuation in ((b'bad',0),(bytes(raw),37)):
            buf=ctypes.create_string_buffer(raw);self.assertFalse(self.lib.audio_profile_adjust(buf,len(raw),attenuation,None))
        for modes,speaker,bluetooth in (((0,2,4,5),False,False),((7,9,11,12),True,False),((28,30,32,33),False,True)):
            for band,mode in enumerate(modes):self.assertEqual(self.lib.audio_profile_word(band,speaker,bluetooth),(mode<<24)|(mode<<16)|5)

    def test_mixer_lifecycle(self):
        subprocess.run([str(self.hw)],env={**os.environ,'E5_NATIVE_ROOT':str(self.root)},check=True,timeout=10)

    def test_sim_snapshot_parity(self):
        old=runpy.run_path(str(TOP/'devices/t551m/tests/reference/sim-status.py'))
        baseline={'+CPIN?':'+CPIN: READY\r\nOK\r\n','+CFUN?':'+CFUN: 1\r\nOK\r\n',
          '+CSCS?;+COPS?':'+CSCS: "UCS2"\r\n+COPS: 0,0,"4E2D56FD79FB52A8",7\r\nOK\r\n',
          '+CEREG?':'+CEREG: 2,1,"1234","ABCD",7\r\nOK\r\n','+C5GREG?':'+C5GREG: 2,0\r\nOK\r\n',
          '+CESQ':'+CESQ: 99,99,255,255,20,60,255,255,255\r\nOK\r\n','+SPENGMD=0,0,6':'1-2-1234-4-5-6-7\r\nOK\r\n'}
        cases=[baseline]
        for key,value in (('+CPIN?','+CPIN: NOT INSERTED\r\n'),('+CPIN?','+CME ERROR: 10\r\n'),('+CPIN?','+CPIN: SIM PIN\r\n'),('+CFUN?','+CFUN: 0\r\n'),('+CESQ','+CESQ: 99,99,255,255,20,60,90,80,70\r\n'),('+CEREG?','OK\r\n'),('+SPENGMD=0,0,6',None),('+CSCS?;+COPS?','+CSCS: "UCS2"\r\n+COPS: 0,0,"D800",7\r\n'),('+CSCS?;+COPS?','+COPS: 0,0,"Numeric 1234",7\r\n')):
            case=copy.deepcopy(baseline);case[key]=value;cases.append(case)
        wire=''.join(json.dumps(c)+'\n' for c in cases)
        result=subprocess.run([str(self.sim)],input=wire,text=True,capture_output=True,check=True)
        for case,line in zip(cases,result.stdout.splitlines()):
            def read(card,cmd):
                if case[cmd] is None:raise RuntimeError('fixture unavailable')
                return case[cmd]
            expected=old['collect'](0,read);expected.pop('updated')
            self.assertEqual(json.loads(line),expected)

    def test_config_read_failure_preserves_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'bin';binary.mkdir()
            config=root/'etc/config';config.mkdir(parents=True)
            for name in ('e5-audio','e5-plugin-phone'):(config/name).write_text('fixture')
            uci=binary/'uci'
            uci.write_text('''#!/bin/sh
[ "$E5_TEST_UCI_FAIL" != 1 ] || exit 2
case "$3" in
 e5-audio) printf "%s\\n" "e5-audio.other.call_volume='15'" "e5-audio.main.call_volume='4'";;
 e5-plugin-phone) printf "%s\\n" "e5-plugin-phone.main.ring_sound='0'" "e5-plugin-phone.main.ring_vibrate='0'" "e5-plugin-phone.main.ring_screen='0'" "e5-plugin-phone.main.ring_tone='beep'";;
esac
''')
            uci.chmod(0o755)
            for failure in (False,True):
                subprocess.run([str(self.bt),'config-error' if failure else 'config'],check=True,timeout=5,
                    env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],
                         'E5_NATIVE_ROOT':tmp,'E5_TEST_UCI_FAIL':'1' if failure else '0'})

    def test_transient_audio_retry_requires_trusted_live_call(self):
        subprocess.run([str(self.bt),'retry'],check=True,timeout=5)

    def test_command_timeout_without_running_main_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            command=Path(tmp)/'e5-test-slow-command'
            command.write_text('#!/bin/sh\nexec sleep 4\n');command.chmod(0o755)
            subprocess.run([str(self.bt),'command-timeout'],check=True,timeout=6,
                env={**os.environ,'PATH':tmp+':'+os.environ['PATH']})

    def test_bluetooth_lease_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'run/e5-hfp';directory.mkdir(parents=True)
            binary=root/'bin';binary.mkdir();log=root/'pactl.log'
            pactl=binary/'pactl'
            pactl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$E5_TEST_COMMANDS"\n[ "$1" != list ] || printf "0 bluez_sink.test module 44100 RUNNING\\n"\n')
            pactl.chmod(0o755)
            for mode in ('ok','reject','cancel','lost','pcm-failed'):
                with self.subTest(mode=mode):
                    log.write_text('');path=directory/'audio.sock'
                    if path.exists():path.unlink()
                    peer=socket.socket(socket.AF_UNIX);peer.bind(str(path));peer.listen(1);peer.settimeout(5)
                    outcomes=[]
                    def serve():
                        try:
                            c,_=peer.accept();c.settimeout(5)
                            with c:
                                request=b''
                                while b'\n' not in request:request+=c.recv(4096)
                                self.assertEqual(json.loads(request),{'acquire':True})
                                if mode=='cancel':time.sleep(.2)
                                else:
                                    c.sendall(json.dumps({'ok':mode!='reject','rate':16000}).encode()+b'\n')
                                    if mode=='lost':time.sleep(.15)
                                if mode!='lost':outcomes.append(c.recv(4096)==b'')
                        except (BrokenPipeError,ConnectionResetError):outcomes.append(True)
                    worker=threading.Thread(target=serve,daemon=True);worker.start()
                    result=subprocess.run([str(self.bt),mode],env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'E5_NATIVE_ROOT':tmp,'E5_TEST_COMMANDS':str(log)},text=True,capture_output=True,timeout=8)
                    worker.join(timeout=6);peer.close();self.assertFalse(worker.is_alive())
                    self.assertEqual(result.returncode,0,result.stderr)
                    commands=log.read_text().splitlines()
                    self.assertEqual(commands.count('suspend-sink bluez_sink.test 1'),1)
                    self.assertEqual(commands.count('suspend-sink bluez_sink.test 0'),1)
                    if mode!='lost':self.assertTrue(all(outcomes))

    def test_voice_events_and_rpc(self):
        import gi
        from gi.repository import Gio,GLib
        daemon=subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1'],stdout=subprocess.PIPE,text=True)
        address=daemon.stdout.readline().strip()
        connection=Gio.DBusConnection.new_for_address_sync(address,Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,None,None)
        connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.ModemManager1',0)),None,0,2000,None)
        modem='/org/freedesktop/ModemManager1/Modem/0';call='/org/freedesktop/ModemManager1/Call/2';voice='org.freedesktop.ModemManager1.Modem.Voice';callif='org.freedesktop.ModemManager1.Call'
        objects={modem:{voice:{'Calls':GLib.Variant('ao',[])}}};snapshots=[]
        interface=Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method></interface></node>').interfaces[0]
        def method(c,s,p,i,m,parameters,invocation):snapshots.append(m);invocation.return_value(GLib.Variant('(a{oa{sa{sv}}})',(objects,)))
        registration=connection.register_object('/org/freedesktop/ModemManager1',interface,method,None,None)
        # Match the real MM export: Calls are separately readable objects,
        # not members of GetManagedObjects(). Keep delayed replies controllable.
        call_properties=Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.freedesktop.DBus.Properties"><method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method></interface></node>').interfaces[0]
        direct_calls={};call_requests=[];delayed=[];hold_call=set();call_registrations=[]
        def call_method(c,s,p,i,m,parameters,invocation):
            self.assertEqual((m,parameters.unpack()),('GetAll',(callif,)))
            call_requests.append(p)
            if p in hold_call:delayed.append((invocation,dict(direct_calls[p])))
            else:invocation.return_value(GLib.Variant('(a{sv})',(direct_calls[p],)))
        loop=GLib.MainLoop();thread=threading.Thread(target=loop.run,daemon=True);thread.start()
        gate=threading.Event();activity={'current':0,'max':0};mutex=threading.Lock()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/api/chunked':
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Transfer-Encoding','chunked');self.end_headers();self.wfile.write(b'4\r\nnull\r\n0\r\n\r\n');return
                if self.path=='/api/slow':
                    with mutex:activity['current']+=1;activity['max']=max(activity['max'],activity['current'])
                    gate.wait(4)
                    with mutex:activity['current']-=1
                data=json.dumps({'path':self.path}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*a):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',8088),Handler);httpthread=threading.Thread(target=server.serve_forever,daemon=True);httpthread.start()
        log=open(self.root/'voice.log','w+')
        process=subprocess.Popen([str(self.voice)],env={**os.environ,'E5_NATIVE_ROOT':str(self.root),'DBUS_SYSTEM_BUS_ADDRESS':address},stdout=log,stderr=log)
        status=self.root/'run/e5-voice-audio/status.json'
        def state():return json.loads(status.read_text())
        def ws(origin='http://127.0.0.1:8088',path='/rpc'):
            s=socket.create_connection(('127.0.0.1',8089),2);s.settimeout(3)
            s.sendall(f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:8089\r\nOrigin: {origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: YWJjZGVmZ2hpamtsbW5vcA==\r\n\r\n'.encode())
            head=b''
            while b'\r\n\r\n' not in head:
                b=s.recv(1)
                if not b:break
                head+=b
            return s,head
        try:
            wait(lambda:status.exists() and 'calls' in state());time.sleep(.15)
            self.assertEqual(state()['calls'],[])
            s,head=ws();self.assertIn(b'101 Switching',head)
            frame(s,'{"id":1,"path":"/api/status"}  ');opcode,wire=receive(s);self.assertEqual(opcode,1);self.assertEqual(json.loads(json.loads(wire)['body']),{'path':'/api/status'})
            frame(s,b'hello',9);self.assertEqual(receive(s),(10,b'hello'))
            frame(s,'{"id":2,',final=False);frame(s,'"path":"/api/calls"}',opcode=0);self.assertEqual(json.loads(receive(s)[1])['status'],200)
            frame(s,b'\x03\xe8',8);self.assertEqual(receive(s),(8,b'\x03\xe8'));s.close()
            s,head=ws();frame(s,'{"id":4,"path":"/api/chunked"}');self.assertEqual(json.loads(receive(s)[1])['body'],'null');s.close()
            s,head=ws()
            for number in range(10,20):frame(s,json.dumps({'id':number,'path':'/api/slow'}))
            busy=[json.loads(receive(s)[1]) for _ in range(2)];self.assertTrue(all(x.get('fallback') for x in busy))
            wait(lambda:activity['current']==4);self.assertEqual(activity['max'],4);gate.set()
            completed=[json.loads(receive(s)[1]) for _ in range(8)];self.assertTrue(all(x['status']==200 for x in completed));s.close()
            s,head=ws(origin='https://untrusted.invalid');self.assertEqual(head,b'');s.close()
            s,head=ws();frame(s,'{"id":3,"path":"http://example.com"}');self.assertEqual(s.recv(1),b'');s.close()
            # Publish a call before its object exists: retain previous state and
            # resnapshot; no fabricated end-of-call or call-control request.
            stream,head=ws(path='/events');self.assertIn(b'200 OK',head);events=stream.makefile('rb')
            initial=json.loads(events.readline().removeprefix(b'data: '));self.assertEqual(initial['calls'],[]);self.assertEqual(events.readline(),b'\n')
            objects[modem][voice]['Calls']=GLib.Variant('ao',[call])
            props={'State':GLib.Variant('u',4),'StateReason':GLib.Variant('u',3),'Direction':GLib.Variant('u',1),'SimSlot':GLib.Variant('u',2),'Number':GLib.Variant('s','test')}
            objects[call]={callif:props}
            connection.emit_signal(None,modem,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(voice,{'Calls':GLib.Variant('ao',[call])},[])))
            wait(lambda:state().get('calls') and state()['calls'][0]['card']==1)
            self.assertEqual(state()['calls'][0]['state'],'active')
            pushed={}
            for _ in range(8):
                line=events.readline()
                if line.startswith(b'data: '):
                    pushed=json.loads(line[6:])
                    if pushed['calls']:break
            self.assertEqual(pushed['calls'][0]['card'],1);events.close();stream.close()
            connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReleaseName',GLib.Variant('(s)',('org.freedesktop.ModemManager1',)),None,0,2000,None)
            wait(lambda:not state()['observer_ready']);self.assertEqual(state()['calls'][0]['state'],'active')
            connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.ModemManager1',0)),None,0,2000,None)
            wait(lambda:state()['observer_ready']);
            count=len(snapshots);time.sleep(2.2);self.assertEqual(len(snapshots),count,'idle observer must not poll MM')
            props['State']=GLib.Variant('u',7)
            connection.emit_signal(None,call,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(callif,{'State':GLib.Variant('u',7)},[])))
            wait(lambda:state()['calls']==[])
            self.assertTrue(all(m=='GetManagedObjects' for m in snapshots))

            direct='/org/freedesktop/ModemManager1/Call/3'
            direct_calls[direct]={**props,'State':GLib.Variant('i',3),'StateReason':GLib.Variant('i',2),'Direction':GLib.Variant('i',1)}
            call_registrations.append(connection.register_object(direct,call_properties,call_method,None,None))
            objects[modem][voice]['Calls']=GLib.Variant('ao',[call,direct])
            connection.emit_signal(None,modem,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(voice,{'Calls':GLib.Variant('ao',[call,direct])},[])))
            wait(lambda:state()['observer_ready'] and state()['calls'] and state()['calls'][0]['id']=='3')
            self.assertEqual(state()['calls'][0]['state'],'ringing-in')
            self.assertNotIn(direct,objects,'Call must remain absent from managed snapshot')
            # Reconnection must hydrate separate Call properties again, then
            # remain event driven while idle rather than repeatedly reading MM.
            connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReleaseName',GLib.Variant('(s)',('org.freedesktop.ModemManager1',)),None,0,2000,None)
            wait(lambda:not state()['observer_ready'])
            before=len(call_requests)
            connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.ModemManager1',0)),None,0,2000,None)
            wait(lambda:state()['observer_ready'] and len(call_requests)>before)
            count=(len(call_requests),len(snapshots));time.sleep(2.2)
            self.assertEqual((len(call_requests),len(snapshots)),count)
            direct_calls[direct]['State']=GLib.Variant('u',7)
            connection.emit_signal(None,direct,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(callif,{'State':GLib.Variant('u',7)},[])))
            wait(lambda:state()['calls']==[])

            raced='/org/freedesktop/ModemManager1/Call/4'
            direct_calls[raced]={**props,'State':GLib.Variant('u',3)}
            hold_call.add(raced)
            call_registrations.append(connection.register_object(raced,call_properties,call_method,None,None))
            objects[modem][voice]['Calls']=GLib.Variant('ao',[raced])
            connection.emit_signal(None,modem,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(voice,{'Calls':GLib.Variant('ao',[raced])},[])))
            wait(lambda:len(delayed)==1)
            direct_calls[raced]['State']=GLib.Variant('u',7)
            connection.emit_signal(None,raced,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(callif,{'State':GLib.Variant('u',7)},[])))
            time.sleep(.1);hold_call.remove(raced)
            invocation,old=delayed.pop();invocation.return_value(GLib.Variant('(a{sv})',(old,)))
            wait(lambda:state()['observer_ready'])
            self.assertEqual(state()['calls'],[],'late ringing reply must not resurrect an ended call')
            self.assertGreaterEqual(call_requests.count(raced),2)
        finally:
            process.terminate();process.wait(timeout=10);gate.set();server.shutdown();server.server_close();loop.quit();thread.join(timeout=3)
            for reg in call_registrations:connection.unregister_object(reg)
            connection.unregister_object(registration);connection.close_sync(None);daemon.terminate();daemon.wait(timeout=5);daemon.stdout.close();log.close()
        self.assertEqual(process.returncode,0,(self.root/'voice.log').read_text())


if __name__=='__main__':unittest.main()
