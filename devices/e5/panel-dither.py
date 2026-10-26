"""Enable E5 ST7365P B9 dithering on bootloader handoff and panel init.

The stock E5 DT opens extended commands with F0 C3/F0 96 and closes them
with F0 3C/F0 69. Keep that protocol and RGB888 transport unchanged.
The B9=02 readback, bootloader handoff and panel reinitialization were tested
on the connected E5 on 2026-10-27. The user confirmed reduced banding.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_dsi_panel.c'
    text = path.read_text()
    helper = Path(__file__).with_name('panel-dither.h').read_text()
    include = '#include "e5-panel-dither.h"\n'
    call = '\n\te5_st7365p_dither(panel);\n'
    anchor = 'static int sprd_panel_enable(struct drm_panel *p)\n'
    init = ('\t\t\t     panel->info.cmds_len[CMD_CODE_INIT]);\n')
    # Validate before changing a reused source cache, including partial patches.
    if text.count(anchor) != 1 or text.count(init) != 1:
        raise ValueError('Unexpected E5 panel initialization source')
    if text.count(include) > 1 or text.count(call) > 1:
        raise ValueError('Duplicate E5 panel dither adaptation')
    if include not in text:
        text = text.replace(anchor, include + '\n' + anchor, 1)
    if call not in text:
        text = text.replace(init, init + call, 1)
    target = path.with_name('e5-panel-dither.h')
    panel_header = path.with_name('sprd_dsi_panel.h')
    host = path.with_name('sprd_dsi.c')
    header_text = panel_header.read_text()
    host_text = host.read_text()
    field = '\tbool e5_dither_applied;\n'
    declaration = 'void sprd_panel_e5_dither_handoff(struct sprd_panel *panel);\n'
    branch = '\tif (dsi->ctx.enabled) {\n\t\tDRM_INFO("dsi is initialized\\n");'
    handoff = '\n\t\tsprd_panel_e5_dither_handoff(panel);'
    field_anchor = '\tbool is_esd_rst;\n'
    decl_anchor = 'int sprd_panel_send_vrefresh_cmd(struct sprd_panel *panel, int index);\n'
    for source, anchor, addition in [(header_text, field_anchor, field),
                                      (header_text, decl_anchor, declaration),
                                      (host_text, branch, handoff)]:
        if source.count(anchor) != 1 or source.count(addition) > 1:
            raise ValueError('Unexpected E5 cold display handoff source')
    if field not in header_text:
        header_text = header_text.replace(field_anchor, field_anchor + field, 1)
    if declaration not in header_text:
        header_text = header_text.replace(decl_anchor, decl_anchor + declaration, 1)
    if handoff not in host_text:
        host_text = host_text.replace(branch, branch + handoff, 1)
    for destination, content in [(panel_header, header_text), (host, host_text)]:
        if destination.read_text() != content:
            destination.write_text(content)
    if not target.exists() or target.read_text() != helper:
        target.write_text(helper)
    if path.read_text() != text:
        path.write_text(text)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
