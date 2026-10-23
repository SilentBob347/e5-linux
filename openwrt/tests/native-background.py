"""Native charger policy and CPU selection, using private files only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
OVERLAY=TOP/'openwrt/overlay'


class NativePolicy(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'config';self.config.mkdir()
        self.state=self.root/'tmp/run/e5-charge';self.state.mkdir(parents=True)
        self.bat=self.root/'sys/class/power_supply/battery';(self.bat/'charger.0').mkdir(parents=True)
        self.hiz=self.root/'sys/class/power_supply/aw322xx_charger/high_impedance_enable';self.hiz.parent.mkdir(parents=True)
        self.hiz.write_text('0');(self.bat/'charger.0/stop_charge').write_text('0')
        (self.bat/'capacity').write_text('90');(self.bat/'status').write_text('Charging')
        usb=self.root/'sys/class/power_supply/usb';usb.mkdir();(usb/'online').write_text('1')
        self.charge_config()

    def charge_config(self,full=False):
        (self.config/'e5-charge').write_text("config charge 'main'\n option enabled '1'\n option stop '80'\n option start '70'\n option full_once '%d'\n"%full)

    def run_code(self,code):
        script=self.root/'main.uc'
        script.write_text("import * as fs from 'fs';\nimport {controller} from "+json.dumps(str(OVERLAY/'usr/libexec/e5-charge-core.uc'))+";\nconst root="+json.dumps(str(self.root))+";\nlet ctl=controller(root,"+json.dumps(str(self.config))+");\n"+code)
        p=subprocess.run(['ucode',str(script)],capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr);return p.stdout

    def test_hysteresis_replug_and_term_restore(self):
        self.run_code('''ctl.init();ctl.tick();
            if(trim(fs.readfile(root+'/tmp/run/e5-charge/stopped'))!='1')die('upper limit');
            fs.writefile(root+'/sys/class/power_supply/battery/capacity','75');ctl.tick();
            if(trim(fs.readfile(root+'/tmp/run/e5-charge/stopped'))!='1')die('hysteresis');
            fs.writefile(root+'/sys/class/power_supply/aw322xx_charger/high_impedance_enable','0');ctl.tick();
            if(trim(fs.readfile(root+'/sys/class/power_supply/aw322xx_charger/high_impedance_enable'))!='1')die('replug');
            fs.writefile(root+'/sys/class/power_supply/battery/capacity','70');ctl.tick();
            if(trim(fs.readfile(root+'/tmp/run/e5-charge/stopped'))!='0')die('resume');
            fs.writefile(root+'/sys/class/power_supply/battery/capacity','90');ctl.tick();ctl.stop();''')
        self.assertEqual(self.hiz.read_text().strip(),'0')
        self.assertEqual((self.bat/'charger.0/stop_charge').read_text().strip(),'0')

    def test_full_once_keeps_charging_and_clears_at_full(self):
        self.charge_config(True)
        self.run_code('''ctl.init();ctl.tick();
            if(trim(fs.readfile(root+'/tmp/run/e5-charge/stopped'))!='0')die('full once');
            fs.writefile(root+'/sys/class/power_supply/battery/status','Full');ctl.tick();
            print(ctl.status());ctl.stop();''')
        self.assertIn("'0'",(self.config/'e5-charge').read_text().split('full_once')[1])

    def test_unplug_and_missing_hiz_keep_existing_manager_control(self):
        self.hiz.unlink()
        self.run_code('''ctl.init();ctl.tick();
            fs.writefile(root+'/sys/class/power_supply/usb/online','0');ctl.tick();
            if(fs.stat(root+'/tmp/run/e5-charge/stopped'))die('unplug state');ctl.stop();''')
        self.assertFalse(self.hiz.exists())

    def test_cpu_placement_only_uses_online_lowest_capacity(self):
        (self.config/'unisoc_modem').write_text("config core 'main'\n option services_cpus 'little'\n")
        for nr,capacity,online in [(0,512,1),(1,512,0),(2,1024,1),(3,512,1)]:
            cpu=self.root/f'sys/devices/system/cpu/cpu{nr}';cpu.mkdir(parents=True)
            (cpu/'cpu_capacity').write_text(str(capacity));(cpu/'online').write_text(str(online))
        def run():
            return subprocess.run(['ucode',str(OVERLAY/'usr/libexec/e5-background-cpus')],
                env=dict(os.environ,E5_CPU_SYSROOT=str(self.root),E5_CPU_CONFIG=str(self.config)),capture_output=True,text=True)
        self.assertEqual(run().stdout.strip(),'0,3')
        (self.config/'unisoc_modem').write_text("config core 'main'\n option services_cpus 'all'\n")
        self.assertEqual(run().stdout.strip(),'all')
        (self.config/'unisoc_modem').write_text("config core 'main'\n option services_cpus 'invalid'\n")
        self.assertNotEqual(run().returncode,0)

    def usb_code(self,code):
        udc=self.root/'sys/class/udc/test';udc.mkdir(parents=True)
        (udc/'state').write_text('not attached');(udc/'soft_connect').write_text('none')
        ext=self.root/'sys/class/extcon/test';ext.mkdir(parents=True);(ext/'state').write_text('USB=1\n')
        usb=self.root/'sys/class/power_supply/usb';(usb/'usb_type').write_text('[SDP] DCP')
        (self.root/'proc').mkdir();(self.root/'proc/uptime').write_text('0.0 0')
        script=self.root/'usb.uc'
        script.write_text("import * as fs from 'fs';\nimport {watchdog} from "+json.dumps(str(OVERLAY/'usr/libexec/e5-usb-watch.uc'))+";\nconst root="+json.dumps(str(self.root))+";let w=watchdog(root);\nfunction at(t){fs.writefile(root+'/proc/uptime',''+t+' 0');return w.tick();}\n"+code)
        p=subprocess.run(['ucode',str(script)],capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr)
        return udc

    def test_usb_recovery_waits_and_caps_attempts_without_touching_network(self):
        self.usb_code('''at(0);at(0);at(1);at(2);
            if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='none')die('early reset');
            at(4);if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='connect')die('missing recovery');
            for(let t=6;t<200;t+=2)at(t);
            fs.writefile(root+'/sys/class/udc/test/soft_connect','sentinel');
            for(let t=200;t<300;t+=2)at(t);
            if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='sentinel')die('unbounded retries');
            w.stop();''')

    def test_usb_soft_replug_restores_on_stop_and_respects_reset_lock(self):
        udc=self.usb_code('''fs.writefile(root+'/sys/class/udc/test/state','addressed');at(0);at(2);at(4);
            if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='disconnect')die('disconnect');
            w.stop();if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='connect')die('stop reconnect');
            fs.mkdir(root+'/tmp/run/e5-usb-reset');fs.mkdir(root+'/tmp/run/e5-usb-reset/lock');
            fs.writefile(root+'/sys/class/udc/test/soft_connect','manual');at(8);at(10);at(12);w.stop();''')
        self.assertEqual((udc/'soft_connect').read_text(),'manual')

    def test_usb_wall_charger_and_configured_host_are_untouched(self):
        self.usb_code('''fs.writefile(root+'/sys/class/power_supply/usb/usb_type','SDP [DCP]');
            for(let t=0;t<40;t+=2)at(t);
            if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='none')die('DCP reset');
            fs.writefile(root+'/sys/class/power_supply/usb/usb_type','[CDP]');
            fs.writefile(root+'/sys/class/udc/test/state','configured');
            for(let t=40;t<80;t+=2)at(t);
            if(trim(fs.readfile(root+'/sys/class/udc/test/soft_connect'))!='none')die('configured reset');''')


if __name__=='__main__':unittest.main()
