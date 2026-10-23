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
from dbus_next import PropertyAccess
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property

MM='org.freedesktop.ModemManager1'
ROOT='/org/freedesktop/ModemManager1'


class Modem(ServiceInterface):
    def __init__(self):super().__init__(MM+'.Modem')
    @dbus_property(access=PropertyAccess.READ)
    def Device(self)->'s':return 'unisoc-sipc'
    @dbus_property(access=PropertyAccess.READ)
    def Plugin(self)->'s':return 'unisoc'
    @dbus_property(access=PropertyAccess.READ)
    def Sim(self)->'o':return ROOT+'/SIM/0'
    @dbus_property(access=PropertyAccess.READ)
    def State(self)->'i':return 8


class Sim(ServiceInterface):
    def __init__(self):super().__init__(MM+'.Sim')
    @dbus_property(access=PropertyAccess.READ)
    def SimIdentifier(self)->'s':return '1234567890123456789'
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
                first=await await_state(lambda s:s['alive'])
                self.assertEqual(first['sim']['iccid'],'1234567890123456789')
                self.assertEqual(state.stat().st_mode&0o777,0o600)
                before=state.stat().st_mtime_ns;await asyncio.sleep(.2)
                self.assertEqual(before,state.stat().st_mtime_ns,'idle mirror rewrites cache')
                sim.emit_properties_changed({'SimIdentifier':'9999999999999999999'})
                await await_state(lambda s:s['sim'].get('iccid')=='9999999999999999999')
                sim.emit_properties_changed({}, ['SimIdentifier'])
                await await_state(lambda s:s['sim'].get('iccid')=='1234567890123456789')
                await bus.release_name(MM)
                await await_state(lambda s:not s['alive'])
                await bus.request_name(MM)
                await await_state(lambda s:s['alive'])
                process.terminate();await asyncio.to_thread(process.wait,3)
                self.assertEqual(process.returncode,0)
                self.assertFalse(state.exists())
            finally:
                if process.poll() is None:process.kill()
                process.communicate(timeout=3)
                bus.disconnect();daemon.terminate();daemon.communicate(timeout=3)


if __name__=='__main__':unittest.main()
