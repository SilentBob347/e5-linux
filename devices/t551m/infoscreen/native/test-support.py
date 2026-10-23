"""Compile production sources on the host; no router or host audio access."""
from pathlib import Path
import io
import shlex
import subprocess
import tarfile

HERE=Path(__file__).resolve().parent
TOP=HERE.parents[3]


def compile_native(directory, name, sources, extra=()):
    directory=Path(directory)
    headers=directory/'json-c'
    if not headers.exists():
        wire=subprocess.check_output(['docker','run','--rm','-v','e5-openwrt-src:/build:ro',
            'debian:trixie','tar','-C','/build/openwrt/staging_dir/target-aarch64_generic_musl/usr/include',
            '-c','json-c'])
        with tarfile.open(fileobj=io.BytesIO(wire)) as archive:
            for member in archive.getmembers():
                if member.isfile():
                    target=directory/member.name
                    if target.parent!=headers:raise ValueError('Unexpected SDK header path')
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gio-2.0'],text=True))
    output=directory/name
    subprocess.run(['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror',
        '-I'+str(directory),'-I'+str(HERE),*map(str,sources),'-o',str(output),
        *extra,*flags,'-l:libjson-c.so.5','-ldl','-lm'],check=True)
    return output
