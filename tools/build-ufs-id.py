#!/usr/bin/env python3
"""Build the static ARM64 READ-DESCRIPTOR helper, recording its source receipt.

Invoke through tools/build-release.py run. This command does not contact a
device, fetch toolchains, create another source tree or package a release.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

TOP=Path(__file__).resolve().parents[1]


def check_static_arm64(data):
    if data[:6]!=b'\x7fELF\x02\x01' or len(data)<64 or struct.unpack_from('<H',data,18)[0]!=183:
        raise ValueError('Expected little-endian ARM64 ELF')
    offset=struct.unpack_from('<Q',data,32)[0]
    size,count=struct.unpack_from('<HH',data,54)
    if size<56 or not count or offset+size*count>len(data):
        raise ValueError('Invalid ELF program headers')
    if any(struct.unpack_from('<I',data,offset+i*size)[0]==3 for i in range(count)):
        raise ValueError('Identity helper must not depend on an Android/OpenWrt loader')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc',default='aarch64-linux-gnu-gcc')
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    config=json.loads((TOP/'tools/build-layout.json').read_text())
    output=a.out or Path(config['ufs_identity_helper'].format(repo=TOP))
    source=TOP/'tools/ufs-id.c'
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.building')
    if temporary.exists():raise ValueError('Retain previous failed helper build for diagnosis: '+str(temporary))
    subprocess.run([a.cc,'-std=gnu11','-Os','-static','-Wall','-Wextra','-Werror',
                    '-o',str(temporary),str(source)],check=True)
    data=temporary.read_bytes();check_static_arm64(data)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=sha:
        raise ValueError('Source changed during helper compilation')
    temporary.replace(output)
    output.with_suffix('.build.json').write_text(json.dumps({
        'format':1,'kind':'ufs-descriptor-v1','source_sha256':sha,
        'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
        'compiler':subprocess.check_output([a.cc,'--version'],text=True).splitlines()[0],
        'static_arm64':True,'hardware_validation':False,
    },indent=2)+'\n')
    print('Verified static read-only UFS identity helper:',output)


if __name__=='__main__':main()
