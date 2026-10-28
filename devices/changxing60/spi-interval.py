"""Match the P720S20 stock SPI minimum inter-word interval.

The actual spi-sprd.ko transfer function enforces a minimum CTL5 value of 9
and reports an interval of 4 * CTL5 + 6 source clocks. The newer controller
driver allows CTL5=1 for the touch transfer. Keep this model-scoped until a
separate hardware trial verifies the effect on touch PRAM integrity.
"""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/spi/spi-sprd.c'
    source = path.read_text()
    marker = '/* P720S20 stock minimum SPI inter-word interval. */'
    if marker in source:
        return
    old = '''\tinterval = DIV_ROUND_UP(word_delay - 10, 4);
\tss->word_delay = interval * 4 + 10;'''
    new = '''\t/* P720S20 stock minimum SPI inter-word interval. */
\tinterval = max_t(u16, DIV_ROUND_UP(word_delay - 10, 4), 9);
\tss->word_delay = interval * 4 + 6;'''
    if source.count(old) != 1:
        raise ValueError('Unexpected P720S20 SPI interval source')
    path.write_text(source.replace(old, new, 1))
