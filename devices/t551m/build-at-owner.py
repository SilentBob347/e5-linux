#!/usr/bin/env python3
"""Build/cache the dedicated arm64 owner using the existing static toolchain."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

TOP=Path(__file__).resolve().parents[2]


def build():
    source=Path(__file__).with_name('atd.c')
    output=TOP/'out/t551m/t551m-atd'
    metadata=output.with_suffix('.build.json')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if metadata.exists() and output.exists():
        saved=json.loads(metadata.read_text())
        if saved.get('source')==digest and saved.get('binary')==hashlib.sha256(output.read_bytes()).hexdigest():
            return output
    output.parent.mkdir(parents=True,exist_ok=True)
    def linux(path):
        if os.name=='nt':
            return subprocess.check_output(['wsl','-d','Ubuntu-22.04','--exec','wslpath','-a','-u',path.as_posix()],text=True).strip()
        return str(path)
    args=[os.environ.get('T551M_CC','aarch64-linux-gnu-gcc'),'-std=c11','-Os','-Wall','-Wextra','-Werror',
          '-static','-s','-o',linux(output),linux(source)]
    if os.name=='nt':args=['wsl','-d','Ubuntu-22.04','--exec',*args]
    subprocess.run(args,check=True)
    data=output.read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(data[18:20],'little')!=183:
        raise ValueError('Compiler did not produce an arm64 ELF executable')
    metadata.write_bytes((json.dumps({'source':digest,'binary':hashlib.sha256(data).hexdigest()})+'\n').encode())
    return output


if __name__=='__main__':print(build())
