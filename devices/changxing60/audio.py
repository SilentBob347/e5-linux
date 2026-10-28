"""Expose the existing AW87xxx profile controls on P720S20's codec card.

The captured HAL selects aw87xxx_profile_switch_0 Receiver/Music. The port
contained that driver's control implementation but never called its exported
registration function; sysfs profiles existed while ALSA had none.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'sound/soc/sprd/unisoc/codec/ump9620/codec/sprd-codec.c'
    text = path.read_text()
    marker = '/* P720S20: register the stock AW87xxx Receiver/Music controls. */'
    if marker in text:
        return
    anchor = 'static int sprd_codec_soc_probe(struct snd_soc_component *codec)'
    if text.count(anchor) != 1:
        raise ValueError('Unexpected UMP9620 codec probe')
    text = text.replace(anchor, 'extern int aw87xxx_add_codec_controls(void *codec);\n\n' + anchor, 1)
    start = text.index(anchor)
    end = text.index('\n/* power down chip */', start)
    probe = text[start:end]
    if probe.count('\n\treturn 0;') != 1:
        raise ValueError('Unexpected codec probe completion')
    probe = probe.replace('\n\treturn 0;', '\n\t' + marker + '\n'
        '\tret = aw87xxx_add_codec_controls(codec);\n'
        '\tif (ret < 0)\n\t\treturn ret;\n\n\treturn 0;', 1)
    path.write_text(text[:start] + probe + text[end:])
