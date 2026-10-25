#!/usr/bin/env python3
"""Bundle musl ARM64 ext4 tools and their ELF dependencies for rooted Android."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


def build(root, out, include_lock=False):
    root = root.resolve()
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        pending = ['usr/sbin/e2fsck', 'usr/sbin/resize2fs', 'lib/ld-musl-aarch64.so.1']
        if include_lock: pending.append('usr/bin/flock')
        hashes = {}
        while pending:
            name = pending.pop()
            if name in hashes:
                continue
            source = root / name
            data = source.read_bytes()
            if data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
                raise ValueError('Expected ARM64 ELF: ' + name)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755)
            hashes[name] = hashlib.sha256(data).hexdigest()
            # OpenWrt sstrip removes section headers. Parse the dynamic segment.
            dynamic = subprocess.check_output(['readelf', '-D', '-d', str(source)], text=True,
                                              stderr=subprocess.DEVNULL)
            for lib in re.findall(r'\(NEEDED\).*\[(.*?)\]', dynamic):
                candidates = [d + '/' + lib for d in ('lib', 'usr/lib') if (root / d / lib).is_file()]
                if not candidates:
                    raise ValueError('Missing dependency: ' + lib)
                pending.append(candidates[0])
        name = 'ext4-geometry.sh'
        data = (Path(__file__).resolve().parent / 'bundle' / name).read_bytes().replace(b'\r\n', b'\n')
        (stage / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
        (stage / 'manifest.json').write_text(json.dumps({'sha256': hashes}, indent=2) + '\n')
        (stage / 'SHA256SUMS').write_text(''.join(v + '  ' + k + '\n' for k, v in sorted(hashes.items())))
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, 'w') as archive:
            for p in sorted(stage.rglob('*')):
                if p.is_file():
                    info = archive.gettarinfo(str(p), arcname=p.relative_to(stage).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = 'root'
                    with p.open('rb') as stream:
                        archive.addfile(info, stream)
        print(out, hashes)


def lock_addon(baseline, full):
    """Keep ext4-tools byte-identical for compatible installer retries."""
    with tarfile.open(fileobj=io.BytesIO(baseline)) as original:
        old={m.name:original.extractfile(m).read() for m in original if m.isfile()}
    additions={}
    with tarfile.open(full) as archive:
        for member in archive:
            if not member.isfile() or member.name in ('manifest.json','SHA256SUMS'):continue
            data=archive.extractfile(member).read()
            if member.name in old:
                if old[member.name]!=data:raise ValueError('Lock addon would replace an existing ext4 dependency: '+member.name)
            else:additions[member.name]=data
    if 'usr/bin/flock' not in additions:raise ValueError('Missing separate flock addon')
    result=io.BytesIO()
    with tarfile.open(fileobj=result,mode='w') as archive:
        hashes={n:hashlib.sha256(v).hexdigest() for n,v in additions.items()}
        additions['INSTALL-LOCK-SHA256SUMS']=''.join(h+'  '+n+'\n' for n,h in sorted(hashes.items())).encode()
        for name,data in sorted(additions.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644 if name=='INSTALL-LOCK-SHA256SUMS' else 0o755
            archive.addfile(info,io.BytesIO(data))
    return result.getvalue()


def build_lock(root,baseline,out):
    with tempfile.TemporaryDirectory() as d:
        full=Path(d)/'all.tar';build(root,full,include_lock=True)
        out.write_bytes(lock_addon(baseline.read_bytes(),full))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--include-lock',action='store_true')
    parser.add_argument('--lock-addon-from',type=Path)
    args = parser.parse_args()
    if args.lock_addon_from:build_lock(args.root,args.lock_addon_from,args.out)
    else:build(args.root, args.out,include_lock=args.include_lock)
