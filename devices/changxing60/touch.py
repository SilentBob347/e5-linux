"""P720S20-only RAM touch + stock display ESD mode4 notification path."""
from pathlib import Path

HERE=Path(__file__).resolve().parent


def apply(kernel):
    kernel=Path(kernel)
    for source,target in (
        ('axs15205.c','drivers/input/touchscreen/axs15205.c'),
        ('sprd_touch_panel.h','include/linux/input/sprd_touch_panel.h'),
    ):
        (kernel/target).write_bytes((HERE/source).read_bytes())
    for name,marker,extra in (
        ('drivers/input/touchscreen/Makefile','CONFIG_TOUCHSCREEN_AXS15205',
         'obj-$(CONFIG_TOUCHSCREEN_AXS15205) += axs15205.o\n'),
        ('drivers/input/touchscreen/Kconfig','config TOUCHSCREEN_AXS15205',
         'config TOUCHSCREEN_AXS15205\n\ttristate "P720S20 AXS15205 RAM SPI touchscreen"\n'
         '\tdepends on SPI && GPIOLIB && DRM_SPRD_DPU0\n\tselect INPUT_MT\n'),
    ):
        p=kernel/name;s=p.read_text()
        if marker not in s:p.write_text(s+'\n'+extra)
    path=kernel/'drivers/unisoc_platform/sprd_disp/sprd_dsi_panel.c'
    text=path.read_text()
    marker='/* P720S20 stock touch-reported ESD mode4. */'
    if marker in text:return
    helpers='''
/* P720S20 stock touch-reported ESD mode4. */
static BLOCKING_NOTIFIER_HEAD(sprd_touch_panel_chain);
static atomic_t sprd_touch_esd = ATOMIC_INIT(0);
int sprd_touch_panel_register(struct notifier_block *nb)
{
    return blocking_notifier_chain_register(&sprd_touch_panel_chain, nb);
}
EXPORT_SYMBOL_GPL(sprd_touch_panel_register);
int sprd_touch_panel_unregister(struct notifier_block *nb)
{
    return blocking_notifier_chain_unregister(&sprd_touch_panel_chain, nb);
}
EXPORT_SYMBOL_GPL(sprd_touch_panel_unregister);
bool sprd_touch_panel_active(void)
{
    return lcd_panel && READ_ONCE(lcd_panel->enabled);
}
EXPORT_SYMBOL_GPL(sprd_touch_panel_active);
void sprd_touch_panel_report_esd(void)
{
    atomic_set(&sprd_touch_esd, 1);
}
EXPORT_SYMBOL_GPL(sprd_touch_panel_report_esd);
'''
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected touch/panel source: '+old[:90])
        text=text.replace(old,new,1)
    replace('#include <linux/backlight.h>',
            '#include <linux/backlight.h>\n#include <linux/atomic.h>\n#include <linux/input/sprd_touch_panel.h>')
    replace('static struct sprd_panel *lcd_panel;', 'static struct sprd_panel *lcd_panel;\n'+helpers)
    # Pause the touch IRQ/heartbeat before LCD sleep/reset, outside panel lock.
    replace('static int sprd_panel_disable(struct drm_panel *p)\n{\n\tstruct sprd_panel *panel = to_sprd_panel(p);',
            'static int sprd_panel_disable(struct drm_panel *p)\n{\n\tstruct sprd_panel *panel = to_sprd_panel(p);\n'
            '\tblocking_notifier_call_chain(&sprd_touch_panel_chain, 0, NULL);')
    replace('\tpanel->info.vrefresh_cmd_changed = true;\n\tmutex_unlock(&panel->lock);',
            '\tpanel->info.vrefresh_cmd_changed = true;\n\tmutex_unlock(&panel->lock);\n'
            '\tatomic_set(&sprd_touch_esd, 0);\n'
            '\tblocking_notifier_call_chain(&sprd_touch_panel_chain, 1, NULL);')
    replace('\telse if (info->esd_check_mode == ESD_MODE_MIX_CHECK)\n\t\tret = sprd_panel_mix_check(panel);',
            '\telse if (info->esd_check_mode == ESD_MODE_MIX_CHECK)\n\t\tret = sprd_panel_mix_check(panel);\n'
            '\telse if (info->esd_check_mode == 4)\n'
            '\t\tret = atomic_xchg(&sprd_touch_esd, 0) ? -EIO : 0;')
    path.write_text(text)
