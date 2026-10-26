"""Offline protocol, policy and staging regression; never accesses hardware."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]


class Port(unittest.TestCase):
    def test_touch_packets_and_current_encoding(self):
        code = r'''
#include <assert.h>
#include <string.h>
#include "touch-packet.h"
#include "charge-current.h"
int main(void) {
    unsigned char p[LYM_PACKET_BYTES] = {0};
    struct lym_point out[LYM_TOUCH_SLOTS];
    assert(lym_decode_touch(p, out) == 0);
    p[2]=1; p[3]=0x81; p[4]=0x40; p[5]=1; p[6]=0xe0;
    assert(lym_decode_touch(p, out) == 1);
    assert(out[0].id == 0 && out[0].x == 320 && out[0].y == 480);
    p[2]=2; p[9]=0; p[10]=25; p[11]=0x10; p[12]=40;
    assert(lym_decode_touch(p, out) == 2 && out[1].id == 1);
    p[9]=0x40; assert(lym_decode_touch(p, out) == 1);
    p[9]=0xc0; assert(lym_decode_touch(p, out) == -1);
    p[9]=0; p[11]=0; assert(lym_decode_touch(p, out) == -1);
    p[11]=0xf0; assert(lym_decode_touch(p, out) == -1);
    p[2]=3; assert(lym_decode_touch(p, out) == -1);
    p[2]=0; assert(lym_decode_touch(p, out) == 0);
    assert(lym_charge_code(0x11,0)==0 && lym_charge_code(0x11,58)==0);
    assert(lym_charge_code(0x11,59)==1 && lym_charge_code(0x11,815)==13);
    assert(lym_charge_code(0x12,1170)==13);
    assert(lym_charge_code(0x11,2875)==50);
    assert(lym_charge_code(0x11,999999)==50);
    assert(lym_charge_code(0x12,999999)==53);
    assert(lym_charge_ma(0x11,13)==815 && lym_charge_ma(0x12,13)==1170);
    for (unsigned id=0x11; id<=0x12; id++) {
        unsigned previous=0;
        for (unsigned ma=0; ma<=5000; ma++) {
            unsigned value=lym_charge_code(id,ma);
            assert(value >= previous && value <= 63);
            previous=value;
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            src, binary = Path(directory)/'test.c', Path(directory)/'test'
            src.write_text(code)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Werror', '-fsanitize=undefined',
                            '-I', str(HERE), str(src), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_touch_prepare_is_repeatable(self):
        apply = runpy.run_path(str(HERE/'touch.py'))['apply']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dest = root/'drivers/input/touchscreen'
            dest.mkdir(parents=True)
            for name in ('Kconfig', 'Makefile'):
                (dest/name).write_text('# fixture\n')
            apply(root)
            before = {p.name: p.read_bytes() for p in dest.iterdir()}
            apply(root)
            self.assertEqual(before, {p.name: p.read_bytes() for p in dest.iterdir()})

    def test_profile_maps_and_donor_isolation(self):
        build = runpy.run_path(str(TOP/'openwrt/build-profile-tf.py'))
        final = runpy.run_path(str(TOP/'openwrt/bundle/finalize-package.py'))
        self.assertEqual(build['MODELS']['lym10k'], ['LYM-10K'])
        self.assertEqual(final['MODELS']['lym10k'], 'LYM-10K')
        self.assertEqual(final['MODELS']['t551m'], 'T551M')
        kernel = (HERE/'build-kernel.sh').read_text()
        self.assertIn('CONFIG_TOUCHSCREEN_TLSC6X=n', kernel)
        self.assertIn('CONFIG_TOUCHSCREEN_LYM10K=m', kernel)
        self.assertIn('CONFIG_COMPAT=y', kernel)
        self.assertIn('CONFIG_COMPAT_32BIT_TIME=y', kernel)
        self.assertNotIn('display-clock.py', (HERE/'prepare-kernel.py').read_text())
        self.assertIn('--preserve-board-current', (HERE/'prepare-kernel.py').read_text())
        self.assertIn("common/musb-host-sink.py", (HERE/'prepare-kernel.py').read_text())
        self.assertIn("charger='bq2560x'", (HERE/'prepare-kernel.py').read_text())
        touch = (HERE/'lym10k-touch.c').read_text()
        self.assertNotIn('request_firmware', touch)
        self.assertIn('INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED', touch)
        self.assertIn('hynitron,hyn_ts', touch)

    def test_staging_keeps_shared_paths_and_existing_profile_behavior(self):
        original = runpy.run_path
        def run(path, *args, **kwargs):
            if Path(path) == TOP/'devices/t551m/infoscreen/stage.py':
                return {'stage': lambda root: None}
            if Path(path) == TOP/'devices/t551m/ui.py':
                ui = original(path, *args, **kwargs)
                ui['stage'].__globals__['PACKAGES'] = {}
                return ui
            return original(path, *args, **kwargs)
        with patch('runpy.run_path', side_effect=run):
            for profile, model in (('lym10k', 'LYM-10K'), ('t512n', 'T512N')):
                with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root/'usr/share/e5-infoscreen').mkdir(parents=True)
                    for name in ('etc/init.d/e5-vendor', 'etc/init.d/e5-sipc-wwan',
                                 'usr/libexec/e5-infoscreen/session', 'usr/share/rpcd/ucode/e5-infoscreen.uc'):
                        p = root/name
                        p.parent.mkdir(parents=True, exist_ok=True)
                        source = TOP/'openwrt/overlay'/name
                        p.write_bytes(source.read_bytes() if source.is_file() else b'fixture')
                    cfg = root/'etc/config/unisoc_modem'
                    cfg.parent.mkdir(parents=True)
                    cfg.write_text("config core 'main'\n option sim2_radio '1'\n")
                    original(str(TOP/f'devices/{profile}/stage.py'))['stage'](root)
                    self.assertEqual((root/'etc/e5/device-profile').read_text().strip(), profile)
                    self.assertEqual((root/'etc/e5/device-model').read_text().strip(), model)
                    self.assertEqual(json.loads((root/'etc/e5/feature-port.json').read_text())['profile'], profile)
                    self.assertEqual(json.loads((root/'etc/e5/feature-port.json').read_text())['vendor_abi'],
                                     'arm' if profile == 'lym10k' else 'arm64')
                    self.assertIn("option sim2_radio '1'", cfg.read_text())
                    self.assertIn("option auto_work_mode_default '152'", cfg.read_text())
                    self.assertNotIn('lte_supported_bands', cfg.read_text())
                    self.assertTrue((root/'etc/init.d/unisoc-battery').is_file())
                    self.assertTrue((root/'etc/rc.d/S14e5-charge-mode').is_symlink())
                    self.assertEqual((root/'opt/e5/e5-data-priority').read_bytes(),
                                     (TOP/'rootfs/overlay/opt/e5/e5-data-priority').read_bytes())
                    self.assertIn('exec /opt/e5/t551m-at', (root/'opt/e5/e5-at').read_text())
                    self.assertIn(profile, (root/'etc/uci-defaults/98-t551m-network-startup').read_text())
                    # Repeated staging is supported and never imports a donor NV.
                    original(str(TOP/f'devices/{profile}/stage.py'))['stage'](root)
                    self.assertFalse((root/'opt/e5/nv').exists())

    def test_cross_profile_staging_refused_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root/'etc/e5/device-profile'
            marker.parent.mkdir(parents=True)
            marker.write_text('t551m\n')
            with self.assertRaises(ValueError):
                runpy.run_path(str(HERE/'stage.py'))['stage'](root)
            self.assertEqual(marker.read_text(), 't551m\n')


if __name__ == '__main__':
    unittest.main()
