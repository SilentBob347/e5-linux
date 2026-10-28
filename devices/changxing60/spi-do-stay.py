"""Match this board's stock SPI data-out idle setting.

The P720S20 stock spi-sprd.ko has the do-stay-value property and its stock DT
does not set it.  The corresponding ZTE driver defaults to mode 2, setting
CTL1 bits 14 and 15.  The current upstream SPI driver omits those bits.
Apply only to the P720S20 build view while validating the AXS touch link.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/spi/spi-sprd.c'
    source = path.read_text()
    marker = '/* P720S20 stock DO-stay default when DT omits do-stay-value. */'
    if marker in source:
        return
    old_define = '#define SPRD_SPI_RTX_MD_MASK\t\tGENMASK(13, 12)'
    new_define = old_define + '\n#define SPRD_SPI_DO_STAY_LASTBIT_MASK\tGENMASK(15, 14)'
    old_setup = '''\tval = readl_relaxed(ss->base + SPRD_SPI_CTL1);
\tval &= ~SPRD_SPI_RTX_MD_MASK;
\tif (t->tx_buf)'''
    new_setup = '''\tval = readl_relaxed(ss->base + SPRD_SPI_CTL1);
\t/* P720S20 stock DO-stay default when DT omits do-stay-value. */
\tval &= ~(SPRD_SPI_RTX_MD_MASK | SPRD_SPI_DO_STAY_LASTBIT_MASK);
\tval |= SPRD_SPI_DO_STAY_LASTBIT_MASK;
\tif (t->tx_buf)'''
    if source.count(old_define) != 1 or source.count(old_setup) != 1:
        raise ValueError('Unexpected P720S20 SPI mode source')
    path.write_text(source.replace(old_define, new_define, 1).replace(old_setup, new_setup, 1))
