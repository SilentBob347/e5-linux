"""Stage every model's shared native runtime into tiny private fixture roots."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
UI=runpy.run_path(str(TOP/'devices/t551m/ui.py'))
REAL_RUN=runpy.run_path


class Staging(unittest.TestCase):
    def test_all_profiles_receive_matching_runtime_and_keep_user_config(self):
        def run(path,*args,**kwargs):
            if Path(path)==TOP/'devices/common/infoscreen/stage.py':
                return {'stage':lambda root:None}  # screen is outside this runtime change
            return REAL_RUN(path,*args,**kwargs)
        with patch.dict(UI['stage'].__globals__,PACKAGES={}):
            with patch('runpy.run_path',side_effect=run):
                for profile in ('e5','t551m','m8','t512n','yuanhang41s','k1','lym10k'):
                    with self.subTest(profile=profile),tempfile.TemporaryDirectory() as td:
                        root=Path(td);config=root/'etc/config/unisoc_modem';config.parent.mkdir(parents=True)
                        config.write_text("config core 'main'\n option services_cpus 'all'\n option fixture_user_setting 'keep'\n")
                        UI['stage'](root,profile=profile)
                        self.assertIn("option fixture_user_setting 'keep'",config.read_text())
                        self.assertIn("option services_cpus 'all'",config.read_text())
                        binary=(root/'opt/e5/t551m-atd').read_bytes()
                        self.assertEqual(binary[:6],b'\x7fELF\x02\x01')
                        self.assertEqual(int.from_bytes(binary[18:20],'little'),183)
                        self.assertEqual(hashlib.sha256(binary).hexdigest(),json.loads((TOP/'out/t551m/t551m-atd.build.json').read_text())['binary'])
                        for name in ('e5-mm-state','e5-background','e5-background-cpus','e5-charge','e5-charge-core.uc','e5-usb-watch','e5-usb-watch.uc'):
                            self.assertEqual((root/'usr/libexec'/name).read_bytes(),(TOP/'openwrt/overlay/usr/libexec'/name).read_bytes())
                        self.assertEqual((root/'usr/lib/e5/vendor/dbus_next-0.2.3-py3-none-any.whl').read_bytes(),
                                         (TOP/'openwrt/overlay/usr/lib/e5/vendor/dbus_next-0.2.3-py3-none-any.whl').read_bytes())
                        self.assertTrue((root/'etc/rc.d/S30e5-mm-state').is_symlink())
                        self.assertTrue((root/'usr/share/rpcd/ucode/e5status.uc').is_file())


if __name__=='__main__':unittest.main()
