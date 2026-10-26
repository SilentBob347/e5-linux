"""Panel source adaptation and real C command/failure sequencing, no hardware."""
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]
adapt = runpy.run_path(str(HERE / 'panel-dither.py'))['apply']
PANEL = 'drivers/unisoc_platform/sprd_disp/sprd_dsi_panel.c'
HEADER = 'struct sprd_panel {\n\tbool is_esd_rst;\n};\nint sprd_panel_send_vrefresh_cmd(struct sprd_panel *panel, int index);\n'
HOST = 'static void encoder_enable(void) {\n\tif (dsi->ctx.enabled) {\n\t\tDRM_INFO("dsi is initialized\\n");\n\t\treturn;\n\t}\n}\n'
FIXTURE = '''static int sprd_panel_enable(struct drm_panel *p)
{
\tmutex_lock(&panel->lock);
\tsprd_panel_send_cmds(panel->slave,
\t\t\t     panel->info.cmds[CMD_CODE_INIT],
\t\t\t     panel->info.cmds_len[CMD_CODE_INIT]);
\tbacklight_update_status(panel->backlight);
}
'''


class Dither(unittest.TestCase):
    def fixture(self, root):
        path = root / PANEL
        path.parent.mkdir(parents=True)
        path.write_text(FIXTURE)
        path.with_name('sprd_dsi_panel.h').write_text(HEADER)
        path.with_name('sprd_dsi.c').write_text(HOST)
        return path

    def test_reapplication_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            adapt(root)
            before = {p: p.read_bytes() for p in path.parent.iterdir()}
            adapt(root)
            self.assertEqual(before, {p: p.read_bytes() for p in path.parent.iterdir()})
            text = path.read_text()
            self.assertLess(text.index('CMD_CODE_INIT]);'), text.index('e5_st7365p_dither(panel);'))
            self.assertLess(text.index('e5_st7365p_dither(panel);'), text.index('backlight_update_status'))
            host = path.with_name('sprd_dsi.c').read_text()
            self.assertLess(host.index('sprd_panel_e5_dither_handoff(panel);'), host.index('return;'))

    def test_unknown_source_is_not_partially_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / PANEL
            path.parent.mkdir(parents=True)
            path.write_text('unexpected layout')
            with self.assertRaises(ValueError):
                adapt(root)
            self.assertEqual(path.read_text(), 'unexpected layout')
            self.assertFalse(path.with_name('e5-panel-dither.h').exists())

    def test_unknown_cold_handoff_does_not_change_other_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.fixture(Path(tmp))
            path.with_name('sprd_dsi.c').write_text('unknown host')
            before = {p: p.read_bytes() for p in path.parent.iterdir()}
            with self.assertRaises(ValueError):
                adapt(Path(tmp))
            self.assertEqual(before, {p: p.read_bytes() for p in path.parent.iterdir()})

    def test_model_isolation_and_build_entries(self):
        for entry, command in [('devices/e5/prepare-kernel.py', 'panel-dither.py'),
                               ('upstream/build-native.sh', 'devices/e5/panel-dither.py'),
                               ('upstream/build.sh', '/e5-policy/panel-dither.py')]:
            self.assertIn(command, (TOP / entry).read_text())
        for model in ('t551m', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k'):
            self.assertNotIn('panel-dither.py', (TOP / f'devices/{model}/prepare-kernel.py').read_text())

    @unittest.skipUnless(shutil.which('cc'), 'Linux host C compiler required')
    def test_real_c_transport_and_error_cleanup(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
typedef uint8_t u8;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DRM_WARN(...) ((void)0)
#define DRM_INFO(...) ((void)0)
struct mipi_dsi_host {int unused;};
struct sprd_dsi { struct mipi_dsi_host host; struct {bool video_lp_cmd_en;} ctx; bool lp; };
struct fake_slave {struct mipi_dsi_host *host;};
struct sprd_panel { struct { const char *of_node; bool use_dcs; } info; struct fake_slave *slave; bool e5_dither_applied; int lock; };
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
#define host_to_dsi(host) container_of(host, struct sprd_dsi, host)
static void mutex_lock(int *lock) { assert(*lock==0);*lock=1; }
static void mutex_unlock(int *lock) { assert(*lock==1);*lock=0; }
static void sprd_dsi_lp_cmd_enable(struct sprd_dsi *dsi,bool enable) {dsi->lp=enable;}
static int writes, reads, fail_at, read_mode, transport, fail_size;
static u8 sent[5][2];
static bool of_node_name_eq(const char *s, const char *name) { return !strcmp(s, name); }
static ssize_t send_command(const void *data, size_t size, int kind) {
    assert(size == 2 && writes < 5 && kind == transport);
    memcpy(sent[writes++], data, 2);
    return writes == fail_at ? -5 : 2;
}
static ssize_t mipi_dsi_dcs_write_buffer(void *d, const void *b, size_t n) { return send_command(b,n,1); }
static ssize_t mipi_dsi_generic_write(void *d, const void *b, size_t n) { return send_command(b,n,0); }
static ssize_t read_command(u8 reg, void *value, size_t n, int kind) {
    assert(reg == 0xb9 && n == 1 && kind == transport);
    reads++; *(u8 *)value = read_mode == 1 ? 0 : 2;
    return read_mode == 2 ? -5 : 1;
}
static ssize_t mipi_dsi_dcs_read(void *d,u8 r,void *v,size_t n) { return read_command(r,v,n,1); }
static ssize_t mipi_dsi_generic_read(void *d,const void *r,size_t rn,void *v,size_t n) {
    assert(rn == 1); return read_command(*(u8 *)r,v,n,0);
}
static int mipi_dsi_set_maximum_return_packet_size(void *d,unsigned short size) {assert(size==1);return fail_size?-5:0;}
#include "panel-dither.h"
int main(void) {
    struct sprd_dsi dsi={0}; struct fake_slave slave={.host=&dsi.host};
    struct sprd_panel panel = {.info.of_node="lcd_st7365p_mipi_hdp",.slave=&slave};
    for (transport=0; transport<2; transport++)
    for (fail_at=0; fail_at<=5; fail_at++)
    for (read_mode=0; read_mode<3; read_mode++) {
        panel.info.use_dcs=transport; writes=reads=0;
        e5_st7365p_dither(&panel);
        assert(writes >= 3);
        assert(sent[writes-2][0]==0xf0 && sent[writes-2][1]==0x3c);
        assert(sent[writes-1][0]==0xf0 && sent[writes-1][1]==0x69);
        if (fail_at==0 || fail_at>3) {
            assert(writes==5 && reads==1);
            assert(sent[2][0]==0xb9 && sent[2][1]==2);
        } else assert(reads==0);
    }
    panel.info.of_node="lcd_ili9488_easyquick_mipi_fhd"; writes=reads=0;
    e5_st7365p_dither(&panel); assert(writes==0 && reads==0);
    sprd_panel_e5_dither_handoff(&panel); assert(writes==0 && reads==0 && !dsi.lp);
    panel.info.of_node="lcd_st7365p_mipi_hdp";panel.info.use_dcs=transport=0;
    fail_at=read_mode=0;writes=reads=0;panel.e5_dither_applied=false;
    sprd_panel_e5_dither_handoff(&panel);
    assert(writes==5 && reads==1 && panel.e5_dither_applied && !dsi.lp && panel.lock==0);
    sprd_panel_e5_dither_handoff(&panel);assert(writes==5 && reads==1);
    writes=reads=0;e5_st7365p_dither(&panel);assert(writes==5 && reads==1 && panel.e5_dither_applied);
    writes=reads=0;fail_size=1;panel.e5_dither_applied=false;
    sprd_panel_e5_dither_handoff(&panel);
    assert(writes==5 && reads==0 && !panel.e5_dither_applied && !dsi.lp && panel.lock==0);
    writes=reads=0;fail_size=0;dsi.ctx.video_lp_cmd_en=true;
    sprd_panel_e5_dither_handoff(&panel);
    assert(writes==5 && reads==1 && panel.e5_dither_applied && dsi.lp && panel.lock==0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(HERE / 'panel-dither.h', root / 'panel-dither.h')
            (root / 'test.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-Werror=implicit-function-declaration',
                            str(root / 'test.c'), '-o', str(root / 'test')], check=True)
            subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    unittest.main()
