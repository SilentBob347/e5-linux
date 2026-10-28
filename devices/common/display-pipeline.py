"""Defer DPHY until its DSI supplier has driver data, before allocating sysfs.

P720S20 first probe: sprd_dphy_probe+0x20c dereferenced a NULL DSI pointer.
This is a supplier-order fix, not a fallback that disables either DSI channel.
"""
from pathlib import Path


def apply(kernel):
    path=Path(kernel)/'drivers/unisoc_platform/sprd_disp/sprd_dphy.c'
    source=path.read_text()
    marker='/* DSI supplier must be bound before creating DPHY devices. */'
    if marker in source:return
    anchor='\tdsi_dev = sprd_disp_pipe_get_input(&pdev->dev);\n\tif (!dsi_dev)\n\t\treturn -ENODEV;'
    late='\tdsi = dev_get_drvdata(dsi_dev);\n\tif (dsi->dual_dsi_en)'
    if source.count(anchor)!=1 or source.count(late)!=1:
        raise ValueError('Unexpected DPHY supplier ordering')
    source=source.replace(late,'\tif (dsi->dual_dsi_en)',1)
    source=source.replace(anchor,anchor+'\n\t'+marker+'\n\tdsi = dev_get_drvdata(dsi_dev);\n\tif (!dsi)\n\t\treturn -EPROBE_DEFER;',1)
    path.write_text(source)
