#!/usr/bin/env python3
"""Reviewed spare-slot diagnostic deployment; requires explicit --execute.

No fastboot, SPD, userdata/GPT or NV writes. Every source, destination and the
32-byte control snapshot is checked before arming. Original files stay on PC.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import secrets
import subprocess
import sys

TOP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOP/'installer'))
from backend import storage


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(backup,probe,previous=None):
    manifest=json.loads((backup/'manifest.json').read_text())
    meta=json.loads(probe.with_suffix('.json').read_text())
    identity=meta['storage_inventory']
    if manifest.get('profile')!='changxing60' or not meta.get('probe') or meta.get('profile')!='changxing60':
        raise ValueError('Expected the captured P720S20 diagnostic image')
    source=manifest['android_slot'];target={'a':'b','b':'a'}[source]
    if (meta['android_slot'],meta['linux_slot'])!=(source,target):raise ValueError('Image/capture slot mismatch')
    # Keep LK/DT/ramdisk counterparts on the same captured stock firmware.
    # Identical partitions are never written just to make a list complete.
    items=[]
    for part in ('uboot','sml','teecfg','trustos','vbmeta','dtb','dtbo','vendor_boot','init_boot'):
        src=part+'_'+source+'.img';dst=part+'_'+target+'.img'
        if manifest['files'][src]['sha256']==manifest['files'][dst]['sha256']:continue
        items.append((part+'_'+target,backup/src,manifest['files'][dst]['sha256']))
    items.append(('boot_'+target,probe,manifest['files']['boot_'+target+'.img']['sha256']))
    for name,path,old in items:
        original=backup/(name+'.img')
        if digest(original)!=old:raise ValueError('Original spare-slot backup changed: '+name)
        if path!=probe and digest(path)!=manifest['files'][path.name]['sha256']:raise ValueError('Stock source changed: '+path.name)
    if digest(backup/'misc-head.bin')!=manifest['files']['misc-head.bin']['sha256']:
        raise ValueError('Original boot control backup changed')
    if probe.stat().st_size!=manifest['files']['boot_'+target+'.img']['bytes']:
        raise ValueError('Probe partition size mismatch')
    expected=meta.get('sha256')
    if not expected or digest(probe)!=expected:raise ValueError('Probe image hash mismatch')
    if previous:
        receipt=json.loads(previous.read_text())
        if (receipt.get('profile'),receipt.get('android_slot'),receipt.get('target_slot'))!=('changxing60',source,target):
            raise ValueError('Previous deployment is for another model/slot')
        known={item['partition']:item['sha256'] for item in receipt['written']}
        items=[(name,path,known.get(name,old)) for name,path,old in items]
    return manifest,meta,identity,items


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb',default='adb');p.add_argument('--serial',required=True)
    p.add_argument('--backup',type=Path,required=True);p.add_argument('--probe',type=Path,required=True)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--previous-deployment',type=Path)
    p.add_argument('--identity-helper',type=Path,required=True)
    a=p.parse_args()
    manifest,meta,identity,items=plan(a.backup,a.probe,a.previous_deployment)
    if digest(a.identity_helper)!=meta['identity_helper_sha256']:raise ValueError('Identity helper differs from probe')
    print(json.dumps({'profile':'changxing60','android_slot':meta['android_slot'],'target_slot':meta['linux_slot'],
        'spare_slot_writes':[{'partition':n,'bytes':p.stat().st_size,'sha256':digest(p)} for n,p,_ in items],
        'misc_write_bytes':32,'userdata_gpt_nv_writes':False,'execute':a.execute},indent=2),flush=True)
    if not a.execute:return
    adb=[a.adb,'-s',a.serial]
    def read(command):return subprocess.check_output(adb+['exec-out','su','-c','stty -onlcr 2>/dev/null; '+command],timeout=180)
    def text(command):return read(command).decode().replace('\r\n','\n').strip()
    if (text('getprop ro.product.model'),text('getprop ro.product.device'),text('getprop ro.boot.slot_suffix'))!=('ZTE 7552N','P720S20','_'+meta['android_slot']):
        raise ValueError('Connected Android model/slot changed; no writes started')
    if text('getprop sys.boot_completed') != '1':
        raise ValueError('Wait for stock Android boot completion and its final USB composition; no writes started')
    query='/data/local/tmp/e5-ufs-id-'+secrets.token_hex(8)
    subprocess.run(adb+['push',str(a.identity_helper),query],check=True)
    try:
        if text('sha256sum '+query).split()[0]!=digest(a.identity_helper):raise ValueError('Identity helper transfer mismatch')
        text('chmod 755 '+query)
        live=storage.parse_inventory(text('export E5_UFS_ID_HELPER='+shlex.quote(query)+'\n'+storage.inventory_script(TOP)))
    finally:text('rm -f '+query)
    if any(live[k]!=identity[k] for k in ('CID','DISK','STORAGE_KIND','DISK_SIZE','START','SIZE','SECTOR_SIZE')):
        raise ValueError('Storage identity/geometry changed; no writes started')
    for name,path,old in items:
        if text('sha256sum /dev/block/by-name/'+name).split()[0]!=old:
            raise ValueError('Spare partition changed since backup: '+name)
    original=bytes.fromhex(meta['fallback_hex'])
    control='dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null'
    if read(control)!=original:raise ValueError('Boot control changed; no writes started')
    remote='/data/local/tmp/changxing60-probe-'+secrets.token_hex(8)
    shell_uid=subprocess.check_output(adb+['shell','id','-u'],timeout=15).decode().strip()
    shell_gid=subprocess.check_output(adb+['shell','id','-g'],timeout=15).decode().strip()
    if not shell_uid.isdecimal() or not shell_gid.isdecimal():raise ValueError('Cannot identify ADB transport user')
    text('set -e; umask 077; mkdir '+remote+'; chown '+shell_uid+':'+shell_gid+' '+remote+'; chmod 700 '+remote)
    receipt=a.probe.with_suffix('.deployment.json')
    state={'profile':'changxing60','android_slot':meta['android_slot'],'target_slot':meta['linux_slot'],
           'probe_sha256':digest(a.probe),'written':[],'remote':remote,'state':'uploading'}
    def save():receipt.write_text(json.dumps(state,indent=2)+'\n')
    save()
    payloads=[]
    for name,path,old in items:
        dest=remote+'/'+name+'.img'
        subprocess.run(adb+['push',str(path),dest],check=True)
        if text('sha256sum '+dest).split()[0]!=digest(path):raise ValueError('Upload checksum mismatch: '+name)
        payloads.append((name,path,dest))
    trial=a.probe.with_suffix('.trial.bin')
    if trial.read_bytes().hex()!=meta['trial_hex']:raise ValueError('Trial control file changed')
    subprocess.run(adb+['push',str(trial),remote+'/trial.bin'],check=True)
    if text('sha256sum '+remote+'/trial.bin').split()[0]!=digest(trial):raise ValueError('Trial control upload mismatch')
    # Recheck the running slot after potentially slow transfers, immediately
    # before the first block write, and again before the final control write.
    def still_android():
        if text('getprop ro.boot.slot_suffix')!='_'+meta['android_slot'] or read(control)!=original:
            raise ValueError('Android/boot control changed while transferring')
    still_android();state['state']='writing';save()
    for name,path,dest in payloads:
        if text('sha256sum /dev/block/by-name/'+name).split()[0]==digest(path):
            state['written'].append({'partition':name,'sha256':digest(path),'already_matched':True});save()
            continue
        text('set -e; dd if='+dest+' of=/dev/block/by-name/'+name+' bs=4M conv=notrunc,fsync')
        if text('sha256sum /dev/block/by-name/'+name).split()[0]!=digest(path):raise ValueError('Partition readback mismatch: '+name)
        state['written'].append({'partition':name,'sha256':digest(path)});save()
    still_android()
    text('set -e; dd if='+remote+'/trial.bin of=/dev/block/by-name/misc bs=1 seek=2048 count=32 conv=notrunc,fsync')
    if read(control)!=trial.read_bytes():raise ValueError('Trial control readback mismatch')
    state['state']='armed';save()
    uploaded=[dest for _,_,dest in payloads]+[remote+'/trial.bin']
    text('rm -f '+' '.join(shlex.quote(x) for x in uploaded)+'; rmdir '+remote)
    print('Verified spare-slot diagnostic armed; rebooting. PC receipt: '+str(receipt),flush=True)
    subprocess.run(adb+['shell','su','-c','sync; reboot'],timeout=20,check=False)


if __name__=='__main__':main()
