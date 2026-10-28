#!/usr/bin/env python3
"""Build a UFS-aware RAM diagnostic; never connects to or flashes a handset."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

TOP=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('backup','kernel','busybox','out'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--current-control',type=Path,help='Exact read-only 32-byte snapshot after an earlier trial; original backup remains intact')
    p.add_argument('--inventory',type=Path,required=True,help='Read-only raw-descriptor inventory')
    p.add_argument('--identity-helper',type=Path,required=True)
    p.add_argument('--touch-firmware',action='store_true',help='Use only this captured easyquick RAM firmware and matching AXS module')
    p.add_argument('--power-test',action='store_true',help='Load the model charger and its FGU/manager in the bounded RAM diagnostic')
    p.add_argument('--ram-ui',action='store_true',help='Enable a checksum-verified RAM userspace handoff; disks remain read-only')
    a=p.parse_args()
    manifest=json.loads((a.backup/'manifest.json').read_text())
    inventory=json.loads(a.inventory.read_text())
    if inventory.get('IDENTITY_KIND')!='ufs-descriptor-v1':raise ValueError('Expected raw UFS descriptor identity')
    if (manifest.get('profile'),manifest.get('board'),inventory.get('STORAGE_KIND'))!=('changxing60','P720S20','ufs'):
        raise ValueError('Wrong model or storage capture')
    android=manifest['android_slot'];target={'a':'b','b':'a'}[android]
    if not re.fullmatch('[0-9a-f]{32}',inventory['CID']):raise ValueError('Missing unique UFS identity')
    for n in ('boot_'+target+'.img','misc-head.bin'):
        if hashlib.sha256((a.backup/n).read_bytes()).hexdigest()!=manifest['files'][n]['sha256']:
            raise ValueError('Stock backup changed: '+n)
    if a.out.exists():raise ValueError('Probe output exists; retain it and choose a reviewed output')
    a.out.parent.mkdir(parents=True,exist_ok=True)
    overlay=a.out.with_suffix('.overlay');(overlay/'etc').mkdir(parents=True,exist_ok=False)
    original=a.current_control.read_bytes() if a.current_control else (a.backup/'misc-head.bin').read_bytes()[2048:2080]
    trial=runpy.run_path(str(TOP/'devices/yuanhang41s/make-probe.py'))['control'](
        original,ord(android)-ord('a'),True)
    (overlay/'etc/android-bc').write_bytes(original)
    (overlay/'etc/storage-identity').write_text(inventory['CID']+'\n')
    (overlay/'etc/storage.sh').write_bytes((TOP/'boot/storage.sh').read_bytes())
    if a.ram_ui:
        handoff=(TOP/'devices/common/probe-ram-root.sh').read_text().replace('PROBE_PROFILE','changxing60')
        # This UFS diagnostic does not write logs to a boot partition tail.
        handoff=handoff.replace('    persist\n','    : # host captures diagnostics; no boot-tail write\n')
        (overlay/'etc/ram-handoff.sh').write_text(handoff)
    utility=overlay/'usr/libexec/e5-ufs-id';utility.parent.mkdir(parents=True)
    utility.write_bytes(a.identity_helper.read_bytes());utility.chmod(0o755)
    if a.touch_firmware:
        name='reference/vendor/firmware/axs_firmware_easyquick.bin'
        firmware=(a.backup/name).read_bytes()
        if hashlib.sha256(firmware).hexdigest()!=manifest['files'][name]['sha256']:
            raise ValueError('Own captured AXS firmware changed')
        destination=overlay/'lib/firmware/axs15205/easyquick.bin'
        destination.parent.mkdir(parents=True);destination.write_bytes(firmware)
    a.out.with_suffix('.trial.bin').write_bytes(trial)
    available={x.stem.replace('-','_'):x for x in (a.kernel/'modules').glob('*.ko')}
    order=[];done=set();pending=set()
    def resolve(name):
        key=Path(name).stem.replace('-','_')
        if key in done:return
        if key in pending:raise ValueError('Module dependency cycle: '+key)
        source=available.get(key)
        if source is None:raise ValueError('Missing matched module: '+name)
        pending.add(key)
        matches=re.findall(rb'\x00depends=([^\x00]*)',source.read_bytes())
        if len(matches)!=1:raise ValueError('Invalid module metadata: '+name)
        for dep in matches[0].decode().split(','):
            if dep:resolve(dep)
        pending.remove(key);done.add(key);order.append(source.name)
    for name in (HERE/'module-order.txt').read_text().split():resolve(name)
    if a.touch_firmware:resolve('axs15205.ko')
    if a.power_test:
        for name in ('ump96xx_fuel_gauge.ko','bq2560x-charger.ko','sprd-charger-manager.ko'):
            resolve(name)
    module_order=a.out.with_suffix('.modules');module_order.write_text(''.join(n+'\n' for n in order))
    subprocess.run([sys.executable,str(TOP/'boot/build-boot-image.py'),
        '--stock-boot',str(a.backup/('boot_'+target+'.img')),'--misc-head',str(a.backup/'misc-head.bin'),
        '--android-slot',android,'--kernel',str(a.kernel/'Image.lk'),'--modules',str(a.kernel/'modules'),
        '--module-order',str(module_order),'--init',str(HERE/'probe-init.sh'),'--overlay',str(overlay),
        '--busybox',str(a.busybox),'--cmdline','','--out',str(a.out)],check=True)
    metadata_path=a.out.with_suffix('.json');metadata=json.loads(metadata_path.read_text())
    metadata.update(profile='changxing60',probe=True,android_slot=android,linux_slot=target,
        kernel_release=(a.kernel/'kernel.release').read_text().strip(),trial_hex=trial.hex(),
        fallback_hex=original.hex(),storage_kind='ufs',logical_block_bytes=inventory['SECTOR_SIZE'],
        storage_inventory=inventory,identity_helper_sha256=hashlib.sha256(a.identity_helper.read_bytes()).hexdigest(),
        hardware_verified=False,device_modified=False,power_test=a.power_test,ram_ui=a.ram_ui,
        root_policy=('RAM only; no Android mount, GPT/NV/modem worker; '
                     + ('model charger/FGU enabled' if a.power_test else 'charger/FGU not loaded')))
    metadata_path.write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':main()
