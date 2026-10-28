"""Restore P720S20 stock SPI PIO FIFO thresholds in the model build view.

The actual spi-sprd.ko stores 0x208 to CTL6 (+0x40) and CTL3 (+0x14)
inside sprd_spi_transfer_one; this was confirmed by disassembly.  The newer
driver omits those per-transfer writes.  Keep this model-scoped until the
touch PRAM readback confirms the effect.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/spi/spi-sprd.c'
    source = path.read_text()
    marker = '/* P720S20 stock SPI FIFO thresholds. */'
    if marker in source:
        return
    anchor = '''\twritel_relaxed(val, ss->base + SPRD_SPI_CTL7);

\t/* factory transfer interrupt reset: a duplex read leaves TX_END set. */'''
    replacement = '''\twritel_relaxed(val, ss->base + SPRD_SPI_CTL7);

\t/* P720S20 stock SPI FIFO thresholds. */
\twritel_relaxed(0x208, ss->base + SPRD_SPI_CTL6);
\twritel_relaxed(0x208, ss->base + SPRD_SPI_CTL3);

\t/* factory transfer interrupt reset: a duplex read leaves TX_END set. */'''
    if source.count(anchor) != 1:
        raise ValueError('Unexpected P720S20 SPI initialization source')
    path.write_text(source.replace(anchor, replacement, 1))
