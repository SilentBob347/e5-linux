"""Remove the unverified SPI timing trial from an existing private build view.

The combined trial was tested in R11 and failed. Keep its rollback separate
from later, individually verified stock-binary register comparisons.
"""
from pathlib import Path


def apply(kernel):
    path=Path(kernel)/'drivers/spi/spi-sprd.c';source=path.read_text()
    marker='/* P720S20 factory inter-word timing and FIFO defaults. */'
    if marker not in source:return
    edits=(
        ('\t/* P720S20 factory inter-word timing and FIFO defaults. */\n'
         '\tinterval = max_t(u16, DIV_ROUND_UP(word_delay - 10, 4), 9);\n'
         '\tss->word_delay = interval * 4 + 6;',
         '\tinterval = DIV_ROUND_UP(word_delay - 10, 4);\n\tss->word_delay = interval * 4 + 10;'),
        ('\twritel_relaxed(0x33f, ss->base + SPRD_SPI_INT_CLR);\n'
         '\twritel_relaxed((2 << 8) | 8, ss->base + SPRD_SPI_CTL6);\n'
         '\twritel_relaxed((2 << 8) | 8, ss->base + SPRD_SPI_CTL3);',
         '\twritel_relaxed(0x33f, ss->base + SPRD_SPI_INT_CLR);'),
        ('\twritel_relaxed(SPRD_SPI_TX_END_INT_CLR | SPRD_SPI_RX_END_INT_CLR,\n'
         '\t\t       ss->base + SPRD_SPI_INT_CLR);',
         '\twritel_relaxed(SPRD_SPI_RX_END_INT_CLR, ss->base + SPRD_SPI_INT_CLR);'),
    )
    for old,new in edits:
        if source.count(old)!=1:raise ValueError('Unexpected P720S20 SPI trial source')
        source=source.replace(old,new,1)
    path.write_text(source)
