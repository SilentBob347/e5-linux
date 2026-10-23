"""Shared screen transport and charger wake must ship on every screen profile."""
from pathlib import Path
import runpy
import tempfile

repo = Path(__file__).resolve().parents[2]
screen = runpy.run_path(str(repo/'devices/t551m/infoscreen/stage.py'))['stage']
with tempfile.TemporaryDirectory() as tmp:
    for profile in ('t551m', 'e5', 'm8', 't512n', 'yuanhang41s', 'k1'):
        root = Path(tmp)/profile
        (root/'etc/e5').mkdir(parents=True)
        (root/'etc/e5/device-profile').write_text(profile+'\n')
        (root/'etc/rc.d').mkdir()
        (root/'etc/uci-defaults').mkdir()
        screen(root)
        index = (root/'usr/share/e5-infoscreen/www/index.html').read_text()
        assert index.count('src="transport.js"') == 1
        assert index.index('transport.js') < index.index('calls.js')
        for name in ('t551m-screen-power','t551m-sim-status','e5-voice-native'):
            elf=(root/'usr/libexec'/name).read_bytes()
            assert elf[:6]==b'\x7fELF\x02\x01' and int.from_bytes(elf[18:20],'little')==183
        assert (root/'usr/share/e5/voice-routes.json').is_file()
        for service in ('t551m-screen-power','t551m-sim-status','e5-voice-audio'):
            assert b'python3' not in (root/'etc/init.d'/service).read_bytes()
        for name in ('calls.js', 'transport.js'):
            assert (root/'usr/share/e5-infoscreen/www'/name).read_bytes() == (repo/'devices/t551m/infoscreen'/name).read_bytes().replace(b'\r\n',b'\n')
        assert b'T551MTransport' in (root/'usr/share/e5-infoscreen/www/sdk/e5.js').read_bytes()
        assert b'T551MCalls.subscribe' in (root/'etc/e5-infoscreen/plugins/phone/phone.js').read_bytes()
        assert (root/'etc/e5/device-profile').read_text().strip() == profile
print('All six screen profiles: shared event/read transport and charger wake PASS')
