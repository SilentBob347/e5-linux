"""Real uloop signals/hotplug events with mock charger/USB files and private ubus."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

TOP=Path(__file__).resolve().parents[2]
LIB=TOP/'openwrt/overlay/usr/libexec'


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.socket=self.root/'ubus.sock'
        self.bus=subprocess.Popen(['/sbin/ubusd','-s',str(self.socket)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(lambda:self.bus.poll() is None and (self.bus.terminate(),self.bus.wait(3)))
        self.wait(lambda:self.socket.exists())
        self.procs=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:p.terminate()
            try:p.communicate(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.communicate()

    def write(self,path,value):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value);return p

    def wait(self,predicate):
        until=time.monotonic()+4
        while time.monotonic()<until:
            try:
                if predicate():return
            except FileNotFoundError:
                pass  # initialization deliberately clears the previous state
            time.sleep(.01)
        self.fail('native event did not reach its completion condition')

    def emit(self,name):
        subprocess.run(['/bin/ubus','-s',str(self.socket),'send',name,'{}'],check=True)

    def launch(self,name,replacement):
        source=(LIB/name).read_text()
        for old,new in replacement.items():source=source.replace(old,new)
        source=source.replace('connect(null,2)','connect('+json.dumps(str(self.socket))+',2)')
        source=source.replace("from './"+name+('-core.uc' if name=='e5-charge' else '.uc')+"'",
                              'from '+json.dumps(str(LIB/(name+('-core.uc' if name=='e5-charge' else '.uc')))))
        script=self.root/(name+'.uc');script.write_text(source)
        p=subprocess.Popen(['ucode',str(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.procs.append(p);return p

    def test_charge_events_idle_and_signal_restore(self):
        hiz=self.write('sys/class/power_supply/aw322xx_charger/high_impedance_enable','0')
        ctl=self.write('sys/class/power_supply/battery/charger.0/stop_charge','0')
        cap=self.write('sys/class/power_supply/battery/capacity','90')
        self.write('sys/class/power_supply/battery/status','Charging')
        self.write('sys/class/power_supply/usb/online','1')
        config=self.write('config/e5-charge',"config charge 'main'\n option enabled '1'\n option start '70'\n option stop '80'\n")
        state=self.write('tmp/run/e5-charge/stopped','0')
        process=self.launch('e5-charge',{'controller()':'controller('+json.dumps(str(self.root))+','+json.dumps(str(config.parent))+')'})
        self.wait(lambda:state.read_text().strip()=='1')
        before=state.stat().st_mtime_ns;time.sleep(.2)
        self.assertEqual(before,state.stat().st_mtime_ns,'idle policy rewrites sysfs/state')
        cap.write_text('70');self.emit('unisoc.battery');self.wait(lambda:state.read_text().strip()=='0')
        cap.write_text('90');self.emit('unisoc.battery');self.wait(lambda:state.read_text().strip()=='1')
        process.terminate();process.wait(timeout=3)
        self.assertEqual(process.returncode,0,process.stderr.read().decode())
        self.assertEqual(hiz.read_text().strip(),'0');self.assertEqual(ctl.read_text().strip(),'0')

    def test_usb_hotplug_and_signal_restore_mid_replug(self):
        self.write('sys/class/udc/test/state','addressed')
        soft=self.write('sys/class/udc/test/soft_connect','none')
        self.write('sys/class/extcon/test/state','USB=1\n')
        self.write('sys/class/power_supply/usb/online','1')
        self.write('sys/class/power_supply/usb/usb_type','[SDP]')
        uptime=self.write('proc/uptime','0.0 0')
        process=self.launch('e5-usb-watch',{'watchdog()':'watchdog('+json.dumps(str(self.root))+')'})
        time.sleep(.1)
        for tick in (2,4):
            uptime.write_text(str(tick)+' 0');self.emit('e5.usb');time.sleep(.05)
        self.wait(lambda:soft.read_text().strip()=='disconnect')
        process.terminate();process.wait(timeout=3)
        self.assertEqual(process.returncode,0,process.stderr.read().decode())
        self.assertEqual(soft.read_text().strip(),'connect')


if __name__=='__main__':unittest.main()
