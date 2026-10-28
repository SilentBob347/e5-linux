"""UMS9620 sprd,ufshc binding. Only explicit UFS profiles call this port."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def apply(kernel):
    kernel=Path(kernel)
    provenance=json.loads((HERE/'ufs/sources.json').read_text())
    for name,expected in provenance['files'].items():
        data=(HERE/'ufs'/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('UFS source hash mismatch: '+name)
        (kernel/'drivers/ufs/host'/name).write_bytes(data)
    additions={
        'drivers/ufs/host/Makefile':('CONFIG_SCSI_UFS_SPRD_QOGIRN6PRO',
            'obj-$(CONFIG_SCSI_UFS_SPRD_QOGIRN6PRO) += ufs-sprd-qogirn6pro.o\n'),
        'drivers/ufs/host/Kconfig':('config SCSI_UFS_SPRD_QOGIRN6PRO',
            'config SCSI_UFS_SPRD_QOGIRN6PRO\n\ttristate "Unisoc QogirN6Pro vendor UFS binding"\n'
            '\tdepends on SCSI_UFSHCD_PLATFORM && OF && ARCH_SPRD\n'
            '\tdepends on NVMEM\n\tselect MFD_SYSCON\n'),
    }
    for name,(marker,addition) in additions.items():
        path=kernel/name;text=path.read_text()
        if marker not in text:path.write_text(text+'\n'+addition)


if __name__=='__main__':
    import sys
    apply(sys.argv[1])
