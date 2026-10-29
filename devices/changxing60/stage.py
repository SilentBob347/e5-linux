#!/usr/bin/env python3
"""Shared handheld UI with P720S20 identity; no M8/41S calibration."""
from pathlib import Path
import json
import runpy
import xml.etree.ElementTree as ET


def scale_session(text):
    command = '/usr/bin/cog -P wl --bg-color=black'
    scaled = command + ' --scale=1.25'
    if text.count(command) != 1:
        raise ValueError('Unexpected screen browser command')
    if scaled in text:
        return text
    if text.split(command, 1)[1].startswith(' --scale='):
        raise ValueError('Unexpected existing browser scale')
    return text.replace(command, scaled, 1)


def stage_screen(root):
    root = Path(root)
    if (root / 'etc/e5/device-profile').read_text().strip() != 'changxing60':
        raise ValueError('Screen profile belongs to another board')
    session = root / 'usr/libexec/e5-infoscreen/session'
    # 480x854 -> 384x683 logical layout; browser scaling also covers apps and
    # touch hit areas. Keep the separate user font-size preference unchanged.
    session.write_text(scale_session(session.read_text()))


def early_module_order(kernel, release):
    """Keep this board's non-symbol suppliers and SPI controller in boot."""
    top = Path(__file__).resolve().parents[2]
    own = (Path(__file__).resolve().parent/'module-order.txt').read_text().split()
    common = (top/'upstream/module-order.txt').read_text().split()
    replacements = {'tlsc6x.ko': 'axs15205.ko', 'aw32257_charger.ko': 'bq2560x-charger.ko'}
    requested = own + [replacements.get(name,name) for name in common]
    return runpy.run_path(str(top/'devices/common/bringup-probe.py'))['module_order'](
        Path(kernel)/'modules', requested, release)


def stage_touch(root):
    path = Path(root)/'etc/modules.d/42-changxing60-touch'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('spi-sprd\naxs15205\n')


def stage(root):
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'm8/stage.py'))['stage'](
        root, profile='changxing60')
    stage_screen(root)
    stage_touch(root)
    root = Path(root)
    (root / 'etc/e5/storage-kind').write_text('ufs\n')
    (root / 'etc/e5/receiver-wiring').write_text('aol\n')
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/stage-ufs.py'))['stage'](root)
    target = root / 'usr/lib/e5/changxing60_audio.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(__file__).read_bytes().replace(b'\r\n', b'\n'))
    service = root / 'etc/init.d/e5-changxing60-audio'
    service.write_text("#!/bin/sh /etc/rc.common\nSTART=18\nstart() { /usr/bin/python3 -c 'from sys import path; path.insert(0, \"/usr/lib/e5\"); from changxing60_audio import stage_audio; stage_audio(\"/\")'; }\n")
    service.chmod(0o755)
    link = root / 'etc/rc.d/S18e5-changxing60-audio'
    if not link.is_symlink(): link.symlink_to('../init.d/e5-changxing60-audio')



def stage_audio(root):
    """Use the recipient HAL routes and gain files after firmware import."""
    root = Path(root)
    if (root / 'etc/e5/device-profile').read_text().strip() != 'changxing60':
        raise ValueError('Audio profile belongs to another board')
    firmware = root / 'lib/firmware'
    xml = ET.parse(firmware / 'changxing60-audio_route.xml').getroot()
    def controls(path):
        node = xml.find(path)
        if node is None:
            raise ValueError('Missing own stock audio route: ' + path)
        result = {n.attrib['name']: n.attrib['val'] for n in node.findall('ctl')}
        if not result:
            raise ValueError('Empty own stock audio route: ' + path)
        return result
    handset = controls('devices/handset/on')
    speaker = controls('devices/speaker/on')
    if handset != speaker or handset.get('Speaker Function') != '1' or handset.get('AOL EAR Sel') != 'AOL':
        raise ValueError('Recipient no longer has the verified shared AOL transducer')
    routes_path = root / 'usr/share/e5/voice-routes.json'
    routes = json.loads(routes_path.read_text())
    microphone = controls('devices/main_mic/on')
    if microphone.get('Mic Function') != '1' or microphone.get('ADD0 DATA SEL') != 'ADD0_DATA_MIC13':
        raise ValueError('Unexpected recipient primary microphone wiring')
    # AUDIO_DEVICE_IN_BUILTIN_MIC=0x80000004 is this factory main_mic route.
    # Do not enable aux/triple microphone or unrelated AP capture usecases.
    routes['ROUTES'] = {**routes['ROUTES'], **microphone}
    routes['CODEC_IIS'] = {**routes['CODEC_IIS'],
                          **controls('vbc_iis_mux/only_codec_p/on'),
                          **controls('vbc_iis_mux/only_codec_c/on')}
    for key, name, device, mode in (('RECEIVER_AOL', 'handset', '0x1', 'Receiver'),
                                    ('SPEAKER', 'speaker', '0x2', 'Music')):
        route = controls('devices/' + name + '/on')
        scene = controls("usecase_device/voice_playback[@device='" + device + "']/on")
        if scene.get('aw87xxx_profile_switch_0') != mode:
            raise ValueError('Unexpected recipient PA profile')
        routes[key] = {**routes['SPEAKER'], **route, **scene}
    routes_path.write_text(json.dumps(routes, separators=(',', ':')) + '\n')
    pga = ET.parse(firmware / 'changxing60-audio_pga.xml').getroot()
    config = ET.parse(firmware / 'changxing60-audio_config.xml').getroot()
    steps = int(config.find('voice_volume').attrib['levels'], 0)
    if not 1 <= steps <= 15:
        raise ValueError('Unsupported recipient voice volume levels')
    gains = {}
    for device, modes in (('Handset', (0, 2, 4, 5)), ('Handsfree', (7, 9, 11, 12))):
        for band, mode in zip(('NB1', 'WB1', 'SWB1', 'FB1'), modes):
            node = pga.find('Audio/' + device + '/' + band + '/VBC_DAC1_DG')
            values = [int(node.find('volume' + str(i)).attrib['val'], 0)
                      for i in range(1, 16)]
            if len(set(values)) != 1 or not 14 <= values[0] <= 127:
                raise ValueError('Unsupported recipient voice PGA curve')
            gains[str(mode)] = values[0]
    routes['VOICE_VOLUME'] = {'steps': steps, 'dac_gain': gains}
    routes_path.write_text(json.dumps(routes, separators=(',', ':')) + '\n')
    maximum = int(pga.find('Music/Handsfree/Playback/VBC_DAC0_DG/volume0').attrib['val'], 0)
    if not 1 <= maximum <= 127:
        raise ValueError('Invalid recipient media gain')
    (firmware / 'changxing60-media-max').write_text(str(maximum) + '\n')
    # Keep the shared playback warm-up, sink volume and notification logic;
    # only replace this board's factory maximum (33 in the captured firmware).
    volume = root / 'usr/libexec/e5-volume'
    text = volume.read_text()
    if 'HW_MAX=' not in text:
        text = text.replace('MAX=15\n', 'MAX=15\nHW_MAX=$(cat /lib/firmware/changxing60-media-max) || exit 1\n')
        text = text.replace('39 - (MAX - $1) * 2', 'HW_MAX - (MAX - $1) * 2').replace('&& g=39', '&& g=$HW_MAX')
        volume.write_text(text)
    ucm = root / 'usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf'
    text = ucm.read_text().replace("VBC DAC0 DG Set' 39,39", "VBC DAC0 DG Set' " + str(maximum) + ',' + str(maximum))
    codec = ET.parse(firmware / 'codec.xml').getroot().find('Music/Handsfree/Playback')
    ao = int(codec.find('ao_playback_volume/volume6').attrib['val'], 0)
    dac = int(codec.find('dacs_playback_volume/volume6').attrib['val'], 0)
    if not 0 <= ao <= 7 or not 0 <= dac <= 3:
        raise ValueError('Invalid recipient codec gains')
    text = text.replace("AO Gain AO Playback Volume' 2", "AO Gain AO Playback Volume' " + str(ao))
    text = text.replace("DAC Gain DAC Playback Volume' 0", "DAC Gain DAC Playback Volume' " + str(dac))
    # The shared E5 UCM omitted TX0 width. Use this recipient's complete
    # physical codec link, not just the equivalent voice-only route manifest.
    marker = '# P720S20 factory codec IIS playback'
    if marker not in text:
        anchor = '\tEnableSequence [\n'
        if text.count(anchor) < 1:
            raise ValueError('Missing UCM verb enable sequence')
        lines = '\t\t' + marker + '\n'
        lines += ''.join('\t\tcset "name=\'' + name + "' " + value + '"\n'
                         for name, value in controls('vbc_iis_mux/only_codec_p/on').items())
        text = text.replace(anchor, anchor + lines, 1)
    ucm.write_text(text)
