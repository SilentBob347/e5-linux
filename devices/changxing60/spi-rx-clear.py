"""Match the P720S20 stock duplex completion interrupt acknowledgement.

The actual spi-sprd.ko writes 0x300 to INT_CLR after RX_END; the newer driver
only clears RX_END. Apply in the P720S20 private kernel view while validating
short two-byte AXS register reads.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/spi/spi-sprd.c'
    source = path.read_text()
    marker = '/* P720S20 stock duplex completion clears both end flags. */'
    if marker in source:
        return
    old = '''\twritel_relaxed(SPRD_SPI_RX_END_INT_CLR, ss->base + SPRD_SPI_INT_CLR);

\treturn 0;
}

static void sprd_spi_tx_req'''
    new = '''\t/* P720S20 stock duplex completion clears both end flags. */
\twritel_relaxed(SPRD_SPI_TX_END_INT_CLR | SPRD_SPI_RX_END_INT_CLR,
\t\t       ss->base + SPRD_SPI_INT_CLR);

\treturn 0;
}

static void sprd_spi_tx_req'''
    if source.count(old) != 1:
        raise ValueError('Unexpected P720S20 SPI RX completion source')
    path.write_text(source.replace(old, new, 1))
