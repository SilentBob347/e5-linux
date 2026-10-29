"""Defer P720S20 panel probe until its actual DPHY supplier is ready.

The installed boot can enumerate DSI before DPHY. The vendor attach returns
EINVAL for that transient condition, after registering an embedded panel0
device backed by devm memory; probe failure then frees that live class device.
Check the supplier before allocating/registering the panel, allowing the
ordinary deferred-probe machinery to retry without leaving panel0 behind.
"""
from pathlib import Path


PREFLIGHT = '''static int sprd_panel_phy_ready(struct mipi_dsi_device *slave)
{
\tstruct device *phy_dev;
\tbool ready;

\tphy_dev = sprd_disp_pipe_get_output(slave->host->dev);
\tif (!phy_dev)
\t\treturn -EPROBE_DEFER;
\tready = dev_get_drvdata(phy_dev) != NULL;
\tput_device(phy_dev);
\treturn ready ? 0 : -EPROBE_DEFER;
}

'''


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_dsi_panel.c'
    source = path.read_text()
    anchor = 'static int sprd_panel_probe(struct mipi_dsi_device *slave)\n'
    if PREFLIGHT not in source:
        if source.count(anchor) != 1:
            raise ValueError('Unexpected P720S20 panel probe')
        source = source.replace(anchor, PREFLIGHT + anchor, 1)
    old = '\tpanel = devm_kzalloc(&slave->dev, sizeof(*panel), GFP_KERNEL);'
    new = ('\t/* A deferred PHY must not leave a freed panel0 class device. */\n'
           '\tret = sprd_panel_phy_ready(slave);\n'
           '\tif (ret)\n\t\treturn ret;\n\n' + old)
    if new not in source:
        if source.count(old) != 1:
            raise ValueError('Unexpected P720S20 panel allocation')
        source = source.replace(old, new, 1)
    path.write_text(source)
