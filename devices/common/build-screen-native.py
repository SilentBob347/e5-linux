#!/usr/bin/env python3
"""Build shared info-screen daemons using the registered OpenWrt toolchain."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

TOP = Path(__file__).resolve().parents[2]
SOURCE = TOP/'devices/t551m/infoscreen/native'
OUT = TOP/'out/native-screen'
TARGETS = {
    't551m-screen-power': ['screen-power.c'],
    't551m-sim-status': ['sim-status.c', 'native-common.c'],
    'e5-voice-native': ['voice.c', 'voice-hardware.c', 'screen-http.c', 'native-common.c'],
}


def route_manifest():
    """One stock-derived route definition for native and Debian CLI runtimes."""
    module=ast.parse((TOP/'rootfs/overlay/opt/e5/e5-call-audio.py').read_text(encoding='utf-8'))
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='VoiceHardware')
    wanted={'ROUTES','RECEIVER','RECEIVER_AOL','SPEAKER','GAINS','PROFILES','BLUETOOTH','BT_SRC','CODEC_IIS'}
    values={n.targets[0].id:ast.literal_eval(n.value) for n in cls.body
            if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in wanted}
    if values.keys()!=wanted:raise ValueError('Incomplete stock-derived native voice routes')
    return (json.dumps(values,ensure_ascii=True,separators=(',',':'))+'\n').encode()


def linux(path):
    if os.name == 'nt':
        return subprocess.check_output(['wsl','-d','Ubuntu-22.04','--exec','wslpath','-a','-u',str(path)],text=True).strip()
    return str(path)


def build(names=None, config_path=None):
    names=list(names or TARGETS)
    layout=Path(config_path or os.environ.get('E5_BUILD_LAYOUT',TOP/'tools/build-layout.json'))
    config=json.loads(layout.read_text(encoding='utf-8'))['native_screen']
    OUT.mkdir(parents=True,exist_ok=True)
    results={}
    for name in names:
        sources=TARGETS[name]
        deps=[SOURCE/s for s in sources]+([] if name=='t551m-screen-power' else [SOURCE/'native.h'])
        inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in deps}
        inputs['builder']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        inputs['toolchain']=config
        for source in sources:
            if not (SOURCE/source).is_file():raise FileNotFoundError(SOURCE/source)
        output=OUT/name;metadata=OUT/(name+'.build.json')
        if output.exists() and metadata.exists():
            saved=json.loads(metadata.read_text())
            if saved.get('inputs')==inputs and saved.get('binary')==hashlib.sha256(output.read_bytes()).hexdigest():
                results[name]=output;continue
        compiler='/build/openwrt/staging_dir/'+config['toolchain']+'/bin/aarch64-openwrt-linux-musl-gcc'
        sysroot='/build/openwrt/staging_dir/target-aarch64_generic_musl'
        args=[compiler,'-std=gnu11','-pthread','-Os','-g0','-Wall','-Wextra','-Werror','-fstack-protector-strong','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-Wl,-z,relro,-z,now','-s']
        if name=='t551m-screen-power':args+=['-static']
        else:args += ['-I'+sysroot+'/usr/include/glib-2.0','-I'+sysroot+'/usr/lib/glib-2.0/include',
                      '-I'+sysroot+'/usr/include','-L'+sysroot+'/usr/lib','-Wl,-rpath-link,'+sysroot+'/usr/lib']
        args += ['/source/'+s for s in sources]+['-o','/out/'+name+'.tmp']
        if name!='t551m-screen-power':args+=['-lgio-2.0','-lgobject-2.0','-lglib-2.0','-ljson-c','-ldl','-lm']
        cmd=['docker','run','--rm','-e','STAGING_DIR=/build/openwrt/staging_dir/target-aarch64_generic_musl','-v',config['volume']+':/build:ro','-v',linux(SOURCE)+':/source:ro','-v',linux(OUT)+':/out',config['image'],*args]
        if os.name=='nt':cmd=['wsl','-d','Ubuntu-22.04','--exec',*cmd]
        subprocess.run(cmd,check=True)
        data=(OUT/(name+'.tmp')).read_bytes()
        if data[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(data[18:20],'little')!=183:raise ValueError('Expected arm64 ELF: '+name)
        (OUT/(name+'.tmp')).replace(output)
        metadata.write_text(json.dumps({'inputs':inputs,'binary':hashlib.sha256(data).hexdigest()},indent=2)+'\n')
        results[name]=output
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('targets',nargs='*')
    args=parser.parse_args()
    for name,path in build(args.targets or None,args.config).items():print(name,path)
