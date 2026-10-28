"""A sink may enumerate before the separate charger/boost provider is bound.

Keep real CC, PHY and explicit DT supply requirements. Acquire the actual
boost regulator before host transition; never substitute a dummy regulator.
Initially enabled only in the P720S20 profile, pending other-board tests.
"""
from pathlib import Path


def apply(kernel):
    path=Path(kernel)/'drivers/usb/dwc3/dwc3-sprd-role.h'
    text=path.read_text()
    marker='/* Sink enumeration does not depend on the boost provider. */'
    if marker in text:return
    old='\t/* Require the actual DT supply; a dummy regulator cannot power OTG. */\n\tr->vbus = devm_regulator_get_optional(dev, "vbus");\n\tif (IS_ERR(r->vbus))\n\t\treturn ERR_CAST(r->vbus);'
    new='\t'+marker+'\n\tif (!of_find_property(dev->of_node, "vbus-supply", NULL))\n\t\treturn ERR_PTR(-ENODEV);'
    anchor='\tif (!host && r->enabled) {'
    if text.count(old)!=1 or text.count(anchor)!=1:raise ValueError('Unexpected DWC3 boost ownership')
    text=text.replace(old,new,1)
    text=text.replace(anchor,'''\tif (host && !r->vbus) {
\t\tr->vbus = devm_regulator_get_optional(r->dev, "vbus");
\t\tif (IS_ERR(r->vbus)) {
\t\t\tret = PTR_ERR(r->vbus);
\t\t\tr->vbus = NULL;
\t\t\tif (ret == -EPROBE_DEFER && ++r->retries < 100)
\t\t\t\tmod_delayed_work(system_wq, &r->work, msecs_to_jiffies(100));
\t\t\tgoto fail;
\t\t}
\t}
''' + anchor,1)
    path.write_text(text)
