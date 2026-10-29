"""Profile isolation and reference contract; no hardware validation."""
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
TOP=HERE.parents[1]


class Profile(unittest.TestCase):
    def test_panel_phy_defer_precedes_allocation_and_is_idempotent(self):
        module=runpy.run_path(str(HERE/'display-ready.py'))
        source='''static int sprd_panel_probe(struct mipi_dsi_device *slave)
{
\tstruct sprd_panel *panel;
\tint ret;
\tpanel = devm_kzalloc(&slave->dev, sizeof(*panel), GFP_KERNEL);
\treturn 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'drivers/unisoc_platform/sprd_disp/sprd_dsi_panel.c'
            path.parent.mkdir(parents=True);path.write_text(source)
            module['apply'](d);result=path.read_text();module['apply'](d)
            self.assertEqual(result,path.read_text())
            body=result[result.index('static int sprd_panel_probe'):]
            self.assertLess(body.index('sprd_panel_phy_ready'),body.index('devm_kzalloc'))
            self.assertIn('put_device(phy_dev)',result)
        prepare=(HERE/'prepare-kernel.py').read_text()
        self.assertIn('changxing60/display-ready.py',prepare)
        for other in ('m8','yuanhang41s','k1','t551m','e5'):
            self.assertNotIn('changxing60/display-ready.py',
                             (TOP/'devices'/other/'prepare-kernel.py').read_text())

    @unittest.skipUnless(shutil.which('cc'),'native C compiler required')
    def test_panel_phy_real_preflight_retries_and_balances_device_reference(self):
        helper=runpy.run_path(str(HERE/'display-ready.py'))['PREFLIGHT']
        fixture='''#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#define EPROBE_DEFER 517
struct device { void *data; };
struct host { struct device *dev; };
struct mipi_dsi_device { struct host *host; };
static struct device phy; static int present, refs;
static struct device *sprd_disp_pipe_get_output(struct device *d) {
 (void)d; if (!present) return NULL; refs++; return &phy;
}
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void put_device(struct device *d) { assert(d==&phy); refs--; }
'''+helper+'''int main(void) {
 struct device d={0}; struct host host={&d}; struct mipi_dsi_device panel={&host};
 assert(sprd_panel_phy_ready(&panel)==-EPROBE_DEFER); assert(refs==0);
 present=1;
 for (int n=0;n<100;n++) assert(sprd_panel_phy_ready(&panel)==-EPROBE_DEFER);
 assert(refs==0); phy.data=&d;
 assert(sprd_panel_phy_ready(&panel)==0); assert(refs==0);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);(path/'test.c').write_text(fixture)
            subprocess.run(['cc','-Wall','-Wextra','-Werror',str(path/'test.c'),'-o',str(path/'test')],check=True)
            subprocess.run([str(path/'test')],check=True)

    def test_config_overrides_donor_hardware(self):
        config=runpy.run_path(str(TOP/'devices/yuanhang41s/build-kernel.py'))['config']
        base='CONFIG_SPRD_UMS9620_CLK=y\nCONFIG_PINCTRL_SPRD_QOGIRN6PRO=y\nCONFIG_LOCALVERSION="-m8-old"\nCONFIG_CHARGER_BQ2560X_SPRD=m\n'
        wanted=config(base,HERE)
        self.assertIn('CONFIG_SCSI_UFS_SPRD_QOGIRN6PRO=y',wanted)
        self.assertIn('CONFIG_SCSI_UFS_BSG=y',wanted)
        self.assertIn('CONFIG_LOCALVERSION="-changxing60-',wanted)
        self.assertNotIn('-m8-old',wanted)
        self.assertIn('CONFIG_CHARGER_BQ2560X_SPRD=m',wanted)
        self.assertNotIn('ignore_unused',wanted)

    def test_display_power_supplier_precedes_consumers(self):
        order=(HERE/'module-order.txt').read_text().splitlines()
        self.assertLess(order.index('sprd_vpu_pw_domain.ko'),order.index('sprd-drm.ko'))

    def test_release_module_order_keeps_spi_and_non_symbol_power_supplier(self):
        module=runpy.run_path(str(HERE/'stage.py'))
        common=(TOP/'upstream/module-order.txt').read_text().split()
        own=(HERE/'module-order.txt').read_text().split()
        replacements={'tlsc6x.ko':'axs15205.ko','aw32257_charger.ko':'bq2560x-charger.ko'}
        with tempfile.TemporaryDirectory() as d:
            kernel=Path(d);modules=kernel/'modules';modules.mkdir()
            for name in set(own+[replacements.get(n,n) for n in common]):
                (modules/name).write_bytes(b'\0vermagic=6.18.test SMP\0depends=\0')
            order=module['early_module_order'](kernel,'6.18.test')
            self.assertEqual(len(order),len(set(order)))
            self.assertLess(order.index('spi-sprd.ko'),order.index('axs15205.ko'))
            self.assertLess(order.index('sprd_vpu_pw_domain.ko'),order.index('sprd-drm.ko'))
            (modules/'spi-sprd.ko').unlink()
            with self.assertRaisesRegex(ValueError,'spi-sprd'):
                module['early_module_order'](kernel,'6.18.test')
            root=kernel/'root';module['stage_touch'](root)
            self.assertEqual((root/'etc/modules.d/42-changxing60-touch').read_text(),
                             'spi-sprd\naxs15205\n')
        builder=(TOP/'openwrt/build-profile-tf.py').read_text()
        self.assertIn("['early_module_order'](a.kernel,release)",builder)

    def test_probe_does_not_use_an_mmc_name_or_mount_android(self):
        text=(HERE/'probe-init.sh').read_text()
        self.assertNotIn('mmcblk',text)
        self.assertNotIn('of=/dev/sda',text)
        self.assertNotIn('mount -t f2fs',text)
        self.assertNotIn('persist()',text)
        self.assertIn('count=32 conv=notrunc,fsync',text)
        self.assertIn('sleep 180; reboot -f',text)

    def test_ufs_port_is_hash_checked_idempotent_and_does_not_change_existing_binding(self):
        apply=runpy.run_path(str(TOP/'devices/common/ufs.py'))['apply']
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host=root/'drivers/ufs/host';host.mkdir(parents=True)
            (host/'Kconfig').write_text('# baseline\n');(host/'Makefile').write_text('# baseline\n')
            (host/'ufs-sprd.c').write_text('original driver')
            apply(root);first={p.name:p.read_bytes() for p in host.iterdir()}
            apply(root);self.assertEqual(first,{p.name:p.read_bytes() for p in host.iterdir()})
            self.assertEqual((host/'ufs-sprd.c').read_text(),'original driver')
            self.assertIn('"sprd,ufshc"',(host/'ufs-sprd-qogirn6pro.c').read_text())

    def test_dphy_supplier_is_checked_before_device_registration(self):
        apply=runpy.run_path(str(TOP/'devices/common/display-pipeline.py'))['apply']
        source='''\tdsi_dev = sprd_disp_pipe_get_input(&pdev->dev);
\tif (!dsi_dev)
\t\treturn -ENODEV;
\tret = sprd_dphy_device_create(dphy, &pdev->dev);
\tdsi = dev_get_drvdata(dsi_dev);
\tif (dsi->dual_dsi_en) { use_dual(); }
'''
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'drivers/unisoc_platform/sprd_disp/sprd_dphy.c'
            path.parent.mkdir(parents=True);path.write_text(source)
            apply(d);result=path.read_text();apply(d)
            self.assertEqual(result,path.read_text())
            self.assertLess(result.index('return -EPROBE_DEFER'),result.index('sprd_dphy_device_create'))
            self.assertEqual(result.count('dsi = dev_get_drvdata'),1)

    def test_dsi_waits_for_payload_after_command_fifo_succeeds(self):
        apply=runpy.run_path(str(TOP/'devices/common/display-dsi-fifo.py'))['apply']
        old='''\tif (!(dsi_wait_tx_cmd_fifo_empty(dsi) &&
\t      dsi_wait_tx_payload_fifo_empty(dsi)))
\t\tpr_err("tx cmd fifo or payload fifo is not empty\\n");'''
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'drivers/unisoc_platform/sprd_disp/dsi/sprd_dsi_api.c'
            path.parent.mkdir(parents=True);path.write_text(old)
            apply(d);result=path.read_text();apply(d)
            self.assertEqual(path.read_text(),result)
            self.assertIn('dsi_wait_tx_cmd_fifo_empty(dsi) ||',result)
            self.assertIn('dsi_wait_tx_payload_fifo_empty(dsi)',result)
            self.assertNotIn('!(dsi_wait_tx_cmd_fifo_empty(dsi) &&',result)

    def test_sink_does_not_require_boost_but_host_still_uses_real_regulator(self):
        apply=runpy.run_path(str(TOP/'devices/common/dwc3-sink-start.py'))['apply']
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'drivers/usb/dwc3/dwc3-sprd-role.h'
            path.parent.mkdir(parents=True);path.write_text((TOP/'devices/m8/dwc3-role.h').read_text())
            apply(d);result=path.read_text();apply(d)
            self.assertEqual(result,path.read_text())
            self.assertIn('if (host && !r->vbus)',result)
            self.assertIn('if (!of_find_property(dev->of_node, "vbus-supply", NULL))',result)
            prepare=result[result.index('static struct sprd_dwc3_role *sprd_dwc3_role_prepare'):]
            self.assertNotIn('devm_regulator_get_optional',prepare)
            self.assertIn('ret == -EPROBE_DEFER',result)

    def test_prepared_slave_reset_uses_registered_platform_device(self):
        fix=runpy.run_path(str(TOP/'devices/common/display-bindings.py'))['slave_platform_owner']
        source='''static int dsi_s_glb_parse_dt(struct dsi_context *ctx,
                                struct device_node *np)
{
\tstruct sprd_dsi *dsi = (struct sprd_dsi *)container_of(ctx,
\t\t\t\t\t\t\tstruct sprd_dsi, ctx);
\ts_ctx_reset = sprd_display_reset_get(&dsi->dev, np, "s_dsi_rst", "reset-syscon");
\treturn 0;
}
static int dsi_core_clk_switch(struct dsi_context *ctx) { return 0; }
'''
        result=fix(source)
        self.assertIn('sprd_display_reset_get(&pdev->dev,',result)
        self.assertNotIn('sprd_display_reset_get(&dsi->dev,',result)
        self.assertIn('of_find_device_by_node(np)',result)
        self.assertEqual(result,fix(result))

    def test_resume_restores_active_framebuffer_and_skips_inactive_crtc(self):
        apply=runpy.run_path(str(TOP/'devices/common/display-resume-planes.py'))['apply']
        source='''\tif (drm_plane->state->crtc->state->active_changed) {
\t\tDRM_DEBUG("resume or suspend, no need to update plane\\n");
\t\treturn;
\t}
'''
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'drivers/unisoc_platform/sprd_disp/sprd_plane.c'
            path.parent.mkdir(parents=True);path.write_text(source)
            apply(d);result=path.read_text();apply(d)
            self.assertEqual(result,path.read_text())
            self.assertNotIn('active_changed',result)
            self.assertIn('if (!drm_state->crtc->state->active)',result)
            path.write_text('unexpected source')
            with self.assertRaises(ValueError):apply(d)


if __name__=='__main__':unittest.main()
