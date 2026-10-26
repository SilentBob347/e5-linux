"""Build the LYM touch driver from source and use its original DT binding."""
from pathlib import Path


def apply(kernel):
    dest = Path(kernel) / 'drivers/input/touchscreen'
    here = Path(__file__).resolve().parent
    for name in ('lym10k-touch.c', 'touch-packet.h'):
        (dest / name).write_bytes((here / name).read_bytes())
    for name, addition in (
        ('Kconfig', '\nconfig TOUCHSCREEN_LYM10K\n\ttristate "LYM-10K Hynitron touch"\n\tdepends on I2C && GPIOLIB\n'),
        ('Makefile', '\nobj-$(CONFIG_TOUCHSCREEN_LYM10K) += lym10k-touch.o\n'),
    ):
        path = dest / name
        text = path.read_text()
        if 'CONFIG_TOUCHSCREEN_LYM10K' not in text and 'config TOUCHSCREEN_LYM10K' not in text:
            path.write_text(text + addition)
