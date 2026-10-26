#!/usr/bin/env python3
"""Make a CID/slot-bound LYM hardware probe, without connecting to a device."""
import argparse
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
REQUESTED = '''sprd_soc_thm.ko sprd_vpu_pw_domain.ko unisoc-iommu.ko
drm_kms_helper.ko drm_dma_helper.ko drm_client_lib.ko ocp2131.ko sprd-drm.ko
sprd_battery_info.ko sprd-charger-manager.ko ump96xx_fuel_gauge.ko
bq2560x-charger.ko lym10k-touch.ko sc27xx-vibra.ko matrix-keymap.ko sprd_keypad.ko'''.split()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('backup', 'kernel', 'busybox', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--stay', type=int, default=90)
    parser.add_argument('--display-test', type=Path)
    parser.add_argument('--ram-handoff', action='store_true')
    args = parser.parse_args()
    runpy.run_path(str(HERE.parent/'common/bringup-probe.py'))['make'](
        args.backup, args.kernel, args.busybox, args.out, 'lym10k', REQUESTED,
        stay=args.stay, display_test=args.display_test, ram_handoff=args.ram_handoff)
