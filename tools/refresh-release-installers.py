#!/usr/bin/env python3
"""Refresh installer-only members of a previously verified local release.

Stream the existing ZIP without extracting boot or rootfs. The firmware keeps
its exact identity; a separate installer revision records the new host inputs.
Called only by tools/build-release.py under its workspace lock.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

TOP=Path(__file__).resolve().parents[1]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def refresh(source,target,tools,revision):
    if target.exists():raise ValueError('Installer refresh target already exists')
    replacement={'files/part-write.sh':(TOP/'openwrt/bundle/part-write.sh').read_bytes().replace(b'\r\n',b'\n'),
                 'files/ext4-tools.tar':tools.read_bytes()}
    with zipfile.ZipFile(source) as original:
        sums={name:checksum for line in original.read('files/SHA256SUMS').decode().splitlines()
              for checksum,name in [line.split(None,1)]}
        payload={n:sums[n] for n in ('files/boot.img','files/openwrt.ext4.gz')}
        record={'format':1,'kind':'installer-only','source_commit':revision['source_commit'],
                'source_fingerprint':revision['source_fingerprint'],'base_archive':source.name,
                'base_sha256':digest(source),'firmware_unchanged':payload,
                'changed':{n:hashlib.sha256(v).hexdigest() for n,v in replacement.items()}}
        replacement['files/INSTALLER-REVISION.json']=(json.dumps(record,indent=2)+'\n').encode()
        replacement['START-HERE.md']=original.read('START-HERE.md')+(
            '\n## Installer revision / 安装器修订\n\n'
            '安装锁现在随进程自动释放，并自动回收旧版失效空锁目录；'
            '真实正在运行的写入仍受保护。系统镜像和 boot 与基础发布包完全一致。\n').encode()
        sums.update({n:hashlib.sha256(v).hexdigest() for n,v in replacement.items()})
        replacement['files/SHA256SUMS']=''.join(h+'  '+n+'\n' for n,h in sorted(sums.items())).encode()
        with zipfile.ZipFile(target,'x') as output:
            for member in original.infolist():
                info=copy.copy(member)
                with output.open(info,'w',force_zip64=True) as destination:
                    if member.filename in replacement:destination.write(replacement[member.filename])
                    else:
                        with original.open(member) as stream:
                            for block in iter(lambda:stream.read(1<<20),b''):destination.write(block)
            for name,data in replacement.items():
                if name in original.namelist():continue
                info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=0o100644<<16
                info.compress_type=zipfile.ZIP_DEFLATED
                output.writestr(info,data)
    return record
