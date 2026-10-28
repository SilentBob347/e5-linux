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


def stage(root):
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'm8/stage.py'))['stage'](
        root, profile='changxing60')
    stage_screen(root)
    root = Path(root)
    (root / 'etc/e5/storage-kind').write_text('ufs\n')
    (root / 'etc/e5/receiver-wiring').write_text('aol\n')
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'common/stage-ufs.py'))['stage'](root)


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
    ucm.write_text(text)
