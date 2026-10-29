"""Execute the prepared PA power hook: media, voice, idle and errors."""
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which('cc'), 'requires a native C compiler')
class Dapm(unittest.TestCase):
    def test_actual_hook_preserves_voice_and_shuts_down_at_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'sound/soc/sprd/unisoc/machine/sprd-asoc-card-utils-hook.c'
            path.parent.mkdir(parents=True)
            path.write_text('static int hook_general_spk(int id, int on)\n{\n\tint gpio, mode;\n#if 0\nLEGACY_SYMBOL_LOOKUP\n#endif\n\treturn 17;\n}\n')
            apply = runpy.run_path(str(HERE/'audio-dapm.py'))['apply']
            apply(root); first = path.read_bytes(); apply(root)
            self.assertEqual(path.read_bytes(), first)
            text = path.read_text()
            text = text[:text.index('#if 0')]+'\n(void)id; (void)gpio; (void)mode; return 17;\n}\n'
            source = root/'test.c'
            source.write_text('''#include <assert.h>
#include <string.h>
#define HOOK_OK 1
int extral_iic_pa_en=2, writes, error;
static char *current="Off";
char *aw87xxx_show_current_profile(int n) { (void)n; return current; }
int aw87xxx_set_profile(int n, char *p) { (void)n; writes++; if(error) return error; current=p; return 0; }
''' + text + '''
int main(void) {
 assert(hook_general_spk(0,1)==HOOK_OK && !strcmp(current,"Music") && writes==1);
 current="Receiver";
 assert(hook_general_spk(0,1)==HOOK_OK && !strcmp(current,"Receiver") && writes==1);
 assert(hook_general_spk(0,0)==HOOK_OK && !strcmp(current,"Off") && writes==2);
 error=-5;
 assert(hook_general_spk(0,1)==-5);
 extral_iic_pa_en=0;
 assert(hook_general_spk(0,1)==17 && writes==3);
 return 0;
}
''')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(root/'test')], check=True)
            subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__': unittest.main()
