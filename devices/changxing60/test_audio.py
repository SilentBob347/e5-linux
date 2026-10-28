"""Stock shared-transducer routing and codec-control registration regressions."""
from pathlib import Path
import json
import runpy
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
stage = runpy.run_path(str(HERE / 'stage.py'))


class Audio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        def put(name, data):
            p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(data)
        put('etc/e5/device-profile', 'changxing60\n')
        put('usr/share/e5/voice-routes.json', json.dumps({'ROUTES':{'Mic Function':'on'}, 'CODEC_IIS':{}, 'SPEAKER': {'Earpiece Function':'off', 'Speaker Function':'on'}}))
        put('usr/libexec/e5-volume', 'MAX=15\ngain() { echo $((39 - (MAX - $1) * 2)); }\n[ x = y ] && g=39\n')
        put('usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf', "VBC DAC0 DG Set' 39,39\nAO Gain AO Playback Volume' 2\nDAC Gain DAC Playback Volume' 0\n")
        put('lib/firmware/changxing60-audio_pga.xml', '<audio_pga><Music><Handsfree><Playback><VBC_DAC0_DG><volume0 val="0x21"/></VBC_DAC0_DG></Playback></Handsfree></Music></audio_pga>')
        put('lib/firmware/codec.xml', '<codec><Music><Handsfree><Playback><ao_playback_volume><volume6 val="0x06"/></ao_playback_volume><dacs_playback_volume><volume6 val="0"/></dacs_playback_volume></Playback></Handsfree></Music></codec>')
        devices = ''.join('<'+tag+'><on><ctl name="Speaker Function" val="1"/><ctl name="AOL EAR Sel" val="AOL"/></on></'+tag+'>' for tag in ('handset', 'speaker'))
        scenes = ''.join('<voice_playback device="'+dev+'"><on><ctl name="aw87xxx_profile_switch_0" val="'+mode+'"/></on></voice_playback>' for dev, mode in (('0x1', 'Receiver'), ('0x2', 'Music')))
        mic = '<main_mic><on><ctl name="Mic Function" val="1"/><ctl name="ADD0 DATA SEL" val="ADD0_DATA_MIC13"/></on></main_mic>'
        mux = '<only_codec_p><on><ctl name="VBC_IIS_TX0_WD_SEL" val="WD_24BIT"/></on></only_codec_p><only_codec_c><on><ctl name="VBC_MUX_ADC1_IIS_PORT_SEL" val="VBC_IIS_PORT_IIS2"/></on></only_codec_c>'
        put('lib/firmware/changxing60-audio_route.xml', '<audio><devices>'+devices+mic+'</devices><usecase_device>'+scenes+'</usecase_device><vbc_iis_mux>'+mux+'</vbc_iis_mux></audio>')

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_endpoint_keeps_distinct_factory_profiles_and_gains(self):
        stage['stage_audio'](self.root)
        path = self.root / 'usr/share/e5/voice-routes.json'
        first = path.read_bytes(); data = json.loads(first)
        for key in ('RECEIVER_AOL', 'SPEAKER'):
            self.assertEqual(data[key]['Speaker Function'], '1')
            self.assertEqual(data[key]['Earpiece Function'], 'off')
        self.assertEqual(data['RECEIVER_AOL']['aw87xxx_profile_switch_0'], 'Receiver')
        self.assertEqual(data['SPEAKER']['aw87xxx_profile_switch_0'], 'Music')
        self.assertEqual(data['ROUTES']['ADD0 DATA SEL'], 'ADD0_DATA_MIC13')
        self.assertEqual(data['CODEC_IIS']['VBC_MUX_ADC1_IIS_PORT_SEL'], 'VBC_IIS_PORT_IIS2')
        self.assertEqual((self.root/'lib/firmware/changxing60-media-max').read_text(), '33\n')
        self.assertIn("AO Gain AO Playback Volume' 6", (self.root/'usr/share/alsa/ucm2/sprdphone-sc273/HiFi.conf').read_text())
        stage['stage_audio'](self.root)
        self.assertEqual(path.read_bytes(), first)

    def test_different_board_or_unrecognized_route_is_rejected(self):
        profile = self.root / 'etc/e5/device-profile'
        profile.write_text('e5')
        with self.assertRaises(ValueError): stage['stage_audio'](self.root)
        profile.write_text('changxing60')
        route = self.root / 'lib/firmware/changxing60-audio_route.xml'
        route.write_text(route.read_text().replace('Receiver', 'Other'))
        with self.assertRaises(ValueError): stage['stage_audio'](self.root)

    def test_control_registration_is_codec_owned_and_idempotent(self):
        path = self.root / 'sound/soc/sprd/unisoc/codec/ump9620/codec/sprd-codec.c'
        path.parent.mkdir(parents=True)
        path.write_text('static int sprd_codec_soc_probe(struct snd_soc_component *codec)\n{\n int ret;\n\treturn 0;\n}\n/* power down chip */\nUNCHANGED\n')
        apply = runpy.run_path(str(HERE/'audio.py'))['apply']
        apply(self.root); first = path.read_bytes(); apply(self.root)
        self.assertEqual(path.read_bytes(), first)
        text = first.decode()
        self.assertEqual(text.count('ret = aw87xxx_add_codec_controls(codec);'), 1)
        self.assertEqual(text.splitlines()[-1], 'UNCHANGED')


if __name__ == '__main__': unittest.main()
