"""Connect P720S20's extral-iic-pa=2 to the existing AW87xxx API.

The imported machine hook leaves the vendor dynamic-symbol branch under #if 0
and falls through to an unconfigured pulse GPIO. Use the actual linked PA;
retain an explicitly selected Receiver/Music profile and power off at idle.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel)/'sound/soc/sprd/unisoc/machine/sprd-asoc-card-utils-hook.c'
    text = path.read_text()
    marker = '/* P720S20: linked I2C PA, no pulse GPIO. */'
    if marker in text:
        return
    anchor = 'static int hook_general_spk(int id, int on)\n{\n\tint gpio, mode;'
    if text.count(anchor) != 1:
        raise ValueError('Unexpected legacy speaker hook')
    replacement = '''extern char *aw87xxx_show_current_profile(int dev_index);
extern int aw87xxx_set_profile(int dev_index, char *profile);

static int hook_general_spk(int id, int on)
{
\tint gpio, mode;
\t/* P720S20: linked I2C PA, no pulse GPIO. */
\tif (extral_iic_pa_en == 2) {
\t\tconst char *profile = aw87xxx_show_current_profile(0);
\t\tint ret;

\t\t/* A voice route may have selected Receiver before PCM startup.
\t\t * Do not replace that explicit selection with the media default.
\t\t */
\t\tif (on && profile && strcmp(profile, "Off"))
\t\t\treturn HOOK_OK;
\t\tret = aw87xxx_set_profile(0, on ? "Music" : "Off");
\t\treturn ret < 0 ? ret : HOOK_OK;
\t}'''
    path.write_text(text.replace(anchor, replacement, 1))
