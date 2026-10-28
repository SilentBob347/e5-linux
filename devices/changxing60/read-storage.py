#!/usr/bin/env python3
"""Capture and cross-check this handset's UFS/GPT without any device writes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import struct
import subprocess
import sys

TOP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOP/'installer'))
from backend import gpt,storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--adb',default='adb')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--identity-helper',type=Path,required=True,help='Registered static ARM64 READ-DESCRIPTOR helper')
    args=parser.parse_args()
    adb=[args.adb,'-s',args.serial,'exec-out','su','-c']
    def read(command):
        return subprocess.check_output(adb+['stty -onlcr 2>/dev/null; '+command],timeout=60)
    def text(command):return read(command).decode().replace('\r\n','\n').strip()
    if (text('getprop ro.product.model'),text('getprop ro.product.device'))!=('ZTE 7552N','P720S20'):
        raise ValueError('Wrong device; expected P720S20')
    helper=args.identity_helper.read_bytes()
    if helper[:5]!=b'\x7fELF\x02' or struct.unpack_from('<H',helper,18)[0]!=183:
        raise ValueError('Expected native ARM64 identity helper')
    remote='/data/local/tmp/e5-ufs-id-'+secrets.token_hex(8)
    subprocess.run([args.adb,'-s',args.serial,'push',str(args.identity_helper),remote],check=True)
    try:
        if text('sha256sum '+remote).split()[0]!=hashlib.sha256(helper).hexdigest():raise ValueError('Helper transfer mismatch')
        text('chmod 755 '+remote)
        info=storage.parse_inventory(text('export E5_UFS_ID_HELPER='+shlex.quote(remote)+'\n'+storage.inventory_script(TOP)))
    finally:
        text('rm -f '+remote)
    if info['STORAGE_KIND']!='ufs':raise ValueError('Expected verified internal UFS topology')
    args.out.mkdir(parents=True,exist_ok=True)
    def checked(command):
        data=read(command)
        expected=text('('+command+') | sha256sum').split()[0]
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Binary transfer checksum mismatch')
        return data
    primary,backup=(checked(c) for c in storage.gpt_header_commands(info))
    front,tail=gpt.gpt_backup_layout(primary,backup,info['DISK_SIZE'])
    disk='/dev/block/'+info['DISK']
    first=checked(f'dd if={disk} bs=512 count={front} 2>/dev/null')
    last=checked(f'dd if={disk} bs=512 skip={tail} count={info["DISK_SIZE"]-tail} 2>/dev/null')
    geometry=gpt.gpt_space(first,last,info['DISK_SIZE'])
    userdata=[p for p in geometry['parts'] if p['name']=='userdata']
    if len(userdata)!=1 or (userdata[0]['start'],userdata[0]['end']+1-userdata[0]['start'])!=(info['START'],info['SIZE']):
        raise ValueError('GPT and live kernel userdata geometry disagree')
    (args.out/'gpt-first.bin').write_bytes(first)
    (args.out/'gpt-last.bin').write_bytes(last)
    (args.out/'storage-inventory.json').write_text(json.dumps(info,indent=2)+'\n')
    (args.out/'gpt-layout.json').write_text(json.dumps(geometry,indent=2)+'\n')
    # Public summary omits the serial descriptor and storage identity digest.
    print(json.dumps({'profile':'changxing60','kind':info['STORAGE_KIND'],'disk':info['DISK'],
        'logical_block_bytes':info['SECTOR_SIZE'],'capacity_gib':round(info['DISK_SIZE']/2097152,3),
        'partitions':len(geometry['parts']),'userdata_gib':round(info['SIZE']/2097152,3),
        'largest_unallocated_gib':round(geometry['largest']/2097152,3),
        'gpt_first_sha256':hashlib.sha256(first).hexdigest(),'gpt_last_sha256':hashlib.sha256(last).hexdigest(),
        'device_modified':False},indent=2))


if __name__=='__main__':main()
