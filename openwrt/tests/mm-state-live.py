"""Actual private D-Bus + production mirror; no modem, user bus or AT access."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOP/'openwrt/overlay/usr/lib/e5/vendor/dbus_next-0.2.3-py3-none-any.whl'))
from dbus_next import Message, MessageType, PropertyAccess, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property

MM='org.freedesktop.ModemManager1'
ROOT='/org/freedesktop/ModemManager1'


class Modem(ServiceInterface):
    def __init__(self):
        super().__init__(MM+'.Modem');self.sim_path=ROOT+'/SIM/0';self.state=8
    @dbus_property(access=PropertyAccess.READ)
    def Device(self)->'s':return 'unisoc-sipc'
    @dbus_property(access=PropertyAccess.READ)
    def Plugin(self)->'s':return 'unisoc'
    @dbus_property(access=PropertyAccess.READ)
    def Sim(self)->'o':return self.sim_path
    @dbus_property(access=PropertyAccess.READ)
    def State(self)->'i':return self.state


class Sim(ServiceInterface):
    def __init__(self,identifier='1234567890123456789'):
        super().__init__(MM+'.Sim');self.identifier=identifier
    @dbus_property(access=PropertyAccess.READ)
    def SimIdentifier(self)->'s':return self.identifier
    @dbus_property(access=PropertyAccess.READ)
    def Imsi(self)->'s':return '460001234567890'


class BusLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_start_properties_owner_loss_reappearance_and_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'run/state.json';(root/'card').write_text('0')
            daemon=subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.addCleanup(daemon.terminate)
            address=daemon.stdout.readline().decode().strip()
            bus=await MessageBus(bus_address=address).connect()
            modem=Modem();sim=Sim();bus.export(ROOT+'/Modem/0',modem);bus.export(ROOT+'/SIM/0',sim)
            bus.export(ROOT+'/SIM/1',Sim())
            bus.export(ROOT+'/SIM/2',Sim('7777777777777777777'))
            reads=[];held=[];hold=[False];fail_once=[True]
            def real_mm_export(message):
                if message.message_type!=MessageType.METHOD_CALL:return
                if message.interface=='org.freedesktop.DBus.ObjectManager' and message.member=='GetManagedObjects':
                    # dbus-next includes all exports by default, unlike real
                    # MM: its SIMs are only readable through Properties.GetAll.
                    properties={'Device':Variant('s','unisoc-sipc'),'Plugin':Variant('s','unisoc'),
                                'Sim':Variant('o',modem.sim_path),'State':Variant('i',modem.state)}
                    return Message.new_method_return(message,'a{oa{sa{sv}}}',[{ROOT+'/Modem/0':{MM+'.Modem':properties}}])
                if message.interface=='org.freedesktop.DBus.Properties' and message.member=='GetAll':
                    reads.append(message.path)
                    if fail_once[0]:
                        fail_once[0]=False
                        return Message.new_error(message,'org.freedesktop.DBus.Error.UnknownObject','not ready')
                    if hold[0]:
                        held.append(message);return True
            bus.add_message_handler(real_mm_export)
            await bus.request_name(MM)
            source=(TOP/'openwrt/overlay/usr/libexec/e5-mm-state').read_text()
            source=source.replace("Path('/run/e5-mm-state')",'Path('+repr(str(root/'run'))+')')
            source=source.replace("Path('/sys/module/sipc_wwan/parameters/card')",'Path('+repr(str(root/'card'))+')')
            source=source.replace('BusType.SYSTEM','BusType.SESSION')
            script=root/'mirror.py';script.write_text(source)
            env=dict(os.environ,DBUS_SESSION_BUS_ADDRESS=address,
                     PYTHONPATH=str(TOP/'openwrt/overlay/usr/lib/e5/vendor/dbus_next-0.2.3-py3-none-any.whl'))
            process=subprocess.Popen([sys.executable,str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            async def await_state(predicate):
                for _ in range(100):
                    self.assertIsNone(process.poll(),process.stderr.read().decode() if process.poll() is not None else '')
                    try:
                        value=json.loads(state.read_text())
                        if predicate(value):return value
                    except (FileNotFoundError,json.JSONDecodeError):pass
                    await asyncio.sleep(.02)
                self.fail('mirror did not publish expected event')
            try:
                first=await await_state(lambda s:s['alive'] and s['sim'].get('iccid'))
                self.assertEqual(first['sim']['iccid'],'1234567890123456789')
                self.assertEqual(len(reads),2,'a newly published SIM should retry its transient GetAll failure')
                self.assertEqual(state.stat().st_mode&0o777,0o600)
                before=state.stat().st_mtime_ns;await asyncio.sleep(.2)
                self.assertEqual(before,state.stat().st_mtime_ns,'idle mirror rewrites cache')
                sim.emit_properties_changed({'SimIdentifier':'9999999999999999999'})
                await await_state(lambda s:s['sim'].get('iccid')=='9999999999999999999')
                sim.emit_properties_changed({}, ['SimIdentifier'])
                await await_state(lambda s:s['sim'].get('iccid')=='1234567890123456789')
                hold[0]=True
                sim.emit_properties_changed({}, ['SimIdentifier'])
                for _ in range(100):
                    if held:break
                    await asyncio.sleep(.01)
                self.assertTrue(held)
                sim.emit_properties_changed({'SimIdentifier':'8888888888888888888'})
                await await_state(lambda s:s['sim'].get('iccid')=='8888888888888888888')
                hold[0]=False
                await bus.send(Message.new_method_return(held.pop(),'a{sv}',[{
                    'SimIdentifier':Variant('s','1234567890123456789'),'Imsi':Variant('s','460001234567890')}]))
                await asyncio.sleep(.15)
                self.assertEqual(json.loads(state.read_text())['sim']['iccid'],'8888888888888888888','stale GetAll replaced a newer identity event')
                # A new referenced path must be hydrated without restarting MM.
                modem.sim_path=ROOT+'/SIM/1'
                modem.emit_properties_changed({'Sim':modem.sim_path})
                await await_state(lambda s:s['sim'].get('iccid')=='1234567890123456789')
                self.assertIn(modem.sim_path,reads)
                # An unrelated State update must not abandon recovery of an
                # invalidated Sim reference while its GetAll is in flight.
                hold[0]=True
                modem.emit_properties_changed({},['Sim'])
                for _ in range(100):
                    if held:break
                    await asyncio.sleep(.01)
                self.assertTrue(held)
                await await_state(lambda s:not s['sim'].get('iccid'))
                hold[0]=False
                modem.state=9;modem.emit_properties_changed({'State':9})
                await await_state(lambda s:s.get('state')==9)
                for request in held:
                    await bus.send(Message.new_method_return(request,'a{sv}',[{
                        'Device':Variant('s','unisoc-sipc'),'Plugin':Variant('s','unisoc'),
                        'Sim':Variant('o',modem.sim_path),'State':Variant('i',8)}]))
                held.clear()
                await await_state(lambda s:s['sim'].get('iccid') and s.get('state')==9)
                # An invalidated reference can resolve to an unseen SIM. Its
                # GetAll completion must chain the next identity read itself.
                modem.sim_path=ROOT+'/SIM/2'
                modem.emit_properties_changed({},['Sim'])
                await await_state(lambda s:s['sim'].get('iccid')=='7777777777777777777')
                await bus.release_name(MM)
                await await_state(lambda s:not s['alive'])
                await bus.request_name(MM)
                await await_state(lambda s:s['alive'] and s['sim'].get('iccid'))
                await asyncio.sleep(.1)  # settle the coalesced owner/interface events
                count=len(reads);before=state.stat().st_mtime_ns;await asyncio.sleep(.2)
                self.assertEqual((len(reads),state.stat().st_mtime_ns),(count,before),'idle mirror must not poll/rewrite')
                process.terminate();await asyncio.to_thread(process.wait,3)
                self.assertEqual(process.returncode,0)
                self.assertFalse(state.exists())
            finally:
                if process.poll() is None:process.kill()
                process.communicate(timeout=3)
                bus.disconnect();daemon.terminate();daemon.communicate(timeout=3)


if __name__=='__main__':unittest.main()
