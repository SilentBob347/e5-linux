"""UMS9620 stock reset-syscon binding and Linux DRM handoff ownership.

P720S20 R6: glb_parse_dt returned before acquiring DPU gates because the DT
uses reset-syscon/vau_reset-syscon, not named reset-controller specifiers.
Its ignored error left NULL gates: cold boot used LK's setup, resume faulted
in dpu_init on MMIO at offset 0x300 after genpd had cycled the domain.
Only explicit profile preparation enables this adaptation.
"""
from pathlib import Path

HERE=Path(__file__).resolve().parent


def slave_platform_owner(source):
    start=source.index('static int dsi_s_glb_parse_dt(')
    end=source.index('static int dsi_core_clk_switch(',start)
    body=source[start:end]
    if '/* Class dsi->dev is not initialized during context parsing. */' in body:
        return source
    old='\tstruct sprd_dsi *dsi = (struct sprd_dsi *)container_of(ctx,\n\t\t\t\t\t\t\tstruct sprd_dsi, ctx);'
    if body.count(old)!=1:raise ValueError('Unexpected DSI slave platform owner')
    body=body.replace(old,'\t/* Class dsi->dev is not initialized during context parsing. */\n'
        '\tstruct platform_device *pdev = of_find_device_by_node(np);\n'
        '\tif (!pdev)\n\t\treturn -ENODEV;',1)
    # Upgrade an already prepared private view without resetting its source.
    body=body.replace('sprd_display_reset_get(&dsi->dev,',
                      'sprd_display_reset_get(&pdev->dev,')
    return source[:start]+body+source[end:]


def apply(kernel):
    kernel=Path(kernel);base=kernel/'drivers/unisoc_platform/sprd_disp'
    (base/'qogirn6pro/display-reset.h').write_bytes((HERE/'display-reset.h').read_bytes())
    for name in ('global_dpu.c','global_dsi.c'):
        path=base/'qogirn6pro'/name;s=path.read_text()
        if '#include "display-reset.h"' in s:
            if name=='global_dsi.c':path.write_text(slave_platform_owner(s))
            continue
        s=s.replace('#include <linux/reset.h>','#include <linux/reset.h>\n#include "display-reset.h"',1)
        s=s.replace('static struct reset_control *','static struct sprd_display_reset *')
        bindings=(
            ('devm_reset_control_get(&pdev->dev, "dpu_ctx_rst")',
             'sprd_display_reset_get(&pdev->dev, np, "dpu_ctx_rst", "reset-syscon")'),
            ('devm_reset_control_get(&pdev->dev, "dpu_vau_rst")',
             'sprd_display_reset_get(&pdev->dev, np, "dpu_vau_rst", "vau_reset-syscon")'),
        ) if name=='global_dpu.c' else (
            ('devm_reset_control_get(&pdev->dev, "dsi_rst")',
             'sprd_display_reset_get(&pdev->dev, np, "dsi_rst", "reset-syscon")'),
            ('devm_reset_control_get(&dsi->dev, "s_dsi_rst")',
             'sprd_display_reset_get(&pdev->dev, np, "s_dsi_rst", "reset-syscon")'),
        )
        for old,new in bindings:
            if s.count(old)!=1:raise ValueError('Unexpected display reset binding: '+name)
            s=s.replace(old,new,1)
        s=s.replace('reset_control_assert(', 'sprd_display_reset_assert(')
        s=s.replace('reset_control_deassert(', 'sprd_display_reset_deassert(')
        if name=='global_dsi.c':
            s=slave_platform_owner(s)
        path.write_text(s)
    path=base/'sprd_dpu.c';s=path.read_text()
    for component in ('clk','glb'):
        old=f'\tif (dpu->{component}->parse_dt)\n\t\tdpu->{component}->parse_dt(ctx, np);'
        new=f'\tif (dpu->{component}->parse_dt) {{\n\t\tret = dpu->{component}->parse_dt(ctx, np);\n\t\tif (ret)\n\t\t\treturn ret;\n\t}}'
        if new not in s:
            if s.count(old)!=1:raise ValueError('Unexpected DPU parse result handling')
            s=s.replace(old,new,1)
    path.write_text(s)
    path=base/'sprd_dsi.c';s=path.read_text()
    old='\tif (dsi->glb->parse_dt)\n\t\tdsi->glb->parse_dt(&dsi->ctx, np);'
    new='\tif (dsi->glb->parse_dt) {\n\t\tint ret = dsi->glb->parse_dt(&dsi->ctx, np);\n\t\tif (ret)\n\t\t\treturn ret;\n\t}'
    if new not in s:
        if s.count(old)!=1:raise ValueError('Unexpected DSI parse result handling')
        s=s.replace(old,new,1)
    path.write_text(s)
    path=base/'sprd_dsi_panel.c';s=path.read_text()
    marker='/* Linux DRM tracks the same live LK handoff as panel->enabled. */'
    if marker not in s:
        old='\tpanel->enabled = true;\n\tlcd_panel = panel;'
        new='''\t/* Linux DRM tracks the same live LK handoff as panel->enabled. */
\tret = regulator_enable(panel->supply);
\tif (ret)
\t\treturn ret;
\tpanel->base.prepared = true;
\tpanel->base.enabled = true;
\tpanel->enabled = true;
\tlcd_panel = panel;'''
        if s.count(old)!=1:raise ValueError('Unexpected DRM panel handoff')
        s=s.replace(old,new,1)
    path.write_text(s)
