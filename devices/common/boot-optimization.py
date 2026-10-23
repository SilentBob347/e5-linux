"""Shared USB descriptor lifetime fix and UMS9620 wake routing module.

Adapted from liuwang97 boot-speed / PR #373 via the MU300 maintenance port.
Only the module's explicit DT match permits register access. Board charger,
display, NV, CPU idle policy and radio sequencing are outside this helper.
"""
from pathlib import Path

HERE=Path(__file__).resolve().parent


def apply(kernel):
    kernel=Path(kernel)
    edits={}
    for name in ('f_ncm.c','f_rndis.c'):
        path=kernel/'drivers/usb/gadget/function'/name
        source=path.read_text()
        # Both error unwind and unbind can free this table. NULL after every
        # free is safe and also makes repeated bind/use=0/unbind safe.
        old='kfree(f->os_desc_table);'
        if old not in source:raise ValueError('Missing USB OS descriptor free: '+name)
        lines=source.splitlines(keepends=True)
        result=[]
        for n,line in enumerate(lines):
            result.append(line)
            if old in line and (n+1==len(lines) or 'f->os_desc_table = NULL;' not in lines[n+1]):
                result.append(line[:len(line)-len(line.lstrip())]+'f->os_desc_table = NULL;\n')
        edits[path]=''.join(result).encode()
    base=kernel/'drivers/soc/sprd'
    edits[base/'ums9620_lpintc.c']=(HERE/'ums9620_lpintc.c').read_bytes()
    for name,marker,addition in (
        ('Makefile','CONFIG_UMS9620_LPINTC','\nobj-$(CONFIG_UMS9620_LPINTC) += ums9620_lpintc.o\n'),
        ('Kconfig','config UMS9620_LPINTC','\nconfig UMS9620_LPINTC\n\ttristate "UMS9620 enabled-SPI cluster wake routing"\n\tdepends on ARM64 && OF && ARM_GIC_V3\n')):
        path=base/name;text=path.read_text()
        if marker not in text:text+=addition
        edits[path]=text.encode()
    for path,data in edits.items():
        if not path.exists() or path.read_bytes()!=data:path.write_bytes(data)


if __name__=='__main__':
    import sys
    apply(sys.argv[1])
