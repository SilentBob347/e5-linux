"""LYM stock current encoding selected by REG0B, not donor board identity."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def apply(kernel):
    replace = runpy.run_path(str(HERE.parent / 't551m/prepare-kernel.py'))['replace_function']
    path = Path(kernel) / 'drivers/power/supply/bq2560x-charger.c'
    text = path.read_text()
    old = 'val != 0x12 || client->addr != 0x6b'
    new = '(val != 0x11 && val != 0x12) || client->addr != 0x6b'
    if old not in text and new not in text:
        raise ValueError('Unknown charger source identity check')
    text = text.replace(old, new).replace('unsupported T551M charger ID', 'unsupported LYM-10K charger ID')
    text = text.replace('"T551M-0x12"', '"LYM-10K"')
    if '#include "lym10k-charge-current.h"' not in text:
        text = '#include "lym10k-charge-current.h"\n' + text
    text = replace(text, 'bq2560x_charger_set_current', '''
\tu8 id, code;
\tint ret = bq2560x_read(info, BQ2560X_REG_B, &id);
\tif (ret) return ret;
\tif (id != 0x11 && id != 0x12) return -ENODEV;
\tcode = lym_charge_code(id, cur / 1000);
\treturn bq2560x_update_bits(info, BQ2560X_REG_2,
\t\tBQ2560X_REG_ICHG_MASK, code);''')
    text = replace(text, 'bq2560x_charger_get_current', '''
\tu8 id, value;
\tint ret = bq2560x_read(info, BQ2560X_REG_B, &id);
\tif (ret) return ret;
\tif (id != 0x11 && id != 0x12) return -ENODEV;
\tret = bq2560x_read(info, BQ2560X_REG_2, &value);
\tif (ret) return ret;
\t*cur = lym_charge_ma(id, value & BQ2560X_REG_ICHG_MASK) * 1000;
\treturn 0;''')
    path.write_text(text)
    (path.parent / 'lym10k-charge-current.h').write_bytes((HERE / 'charge-current.h').read_bytes())
