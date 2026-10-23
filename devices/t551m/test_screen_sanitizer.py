"""Native mixer lifecycle under ASan/UBSan/LSan, with fake ALSA only."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent/'infoscreen/native'
TOP=HERE.parents[3]
support=runpy.run_path(str(HERE/'test-support.py'))
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    routes=root/'usr/share/e5/voice-routes.json';routes.parent.mkdir(parents=True)
    routes.write_bytes(runpy.run_path(str(TOP/'devices/common/build-screen-native.py'))['route_manifest']())
    binary=support['compile_native'](root,'hardware-sanitizer',
        [HERE/'test-hardware.c',HERE/'native-common.c'],
        ['-fsanitize=address,undefined','-fno-omit-frame-pointer'])
    subprocess.run([str(binary)],check=True,timeout=15,env={**os.environ,
        'E5_NATIVE_ROOT':tmp,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1',
        'UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'})
print('Native mixer ASan/UBSan/LSan: PASS')
