"""Exercise M8 revision encoding and the actual downstream charger adapters."""
from pathlib import Path
import os
import re
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
RAW = HERE / 'port/drivers/power/supply/bq2560x-charger.c'
apply = runpy.run_path(str(HERE / 'charger.py'))['apply']
prepare = runpy.run_path(str(HERE / 'prepare-kernel.py'))['prepare_charger']


def generated(body):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        supply = root / 'drivers/power/supply'
        supply.mkdir(parents=True)
        (supply / 'bq2560x-charger.c').write_bytes(RAW.read_bytes())
        (supply / 'Kconfig').write_text('')
        (supply / 'Makefile').write_text('')
        body(root)
        return (supply / 'bq2560x-charger.c').read_text()


def function(source, name):
    match = re.search(r'static (?:int|bool|void)\s+' + name + r'\([^;{}]*\)\s*\{', source)
    if not match:
        raise AssertionError('Missing function ' + name)
    index, depth = match.end(), 1
    while depth:
        depth += (source[index] == '{') - (source[index] == '}')
        index += 1
    return source[match.start():index]


def compile_run(source):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'test.c').write_text(source)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


class Charger(unittest.TestCase):
    def test_revision_is_selected_by_recipient_not_donor_label(self):
        normal = generated(lambda root: apply(root))
        self.assertNotIn('u8 chip_rev;', normal)
        for recipient in ('yuanhang41s', 'k1', 'changxing60'):
            self.assertEqual(generated(lambda root: prepare(root, recipient)), normal)
        m8 = generated(lambda root: prepare(root, 'm8'))
        self.assertIn('val != 0x11 && val != 0x12', m8)
        self.assertIn('info->chip_rev = val;', m8)
        self.assertLess(m8.index('info->chip_rev = val;'),
                        m8.index('ret = bq2560x_charger_hw_init(info);'))

    def test_custom_board_adapter_keeps_its_own_contract(self):
        calls = []
        prepare('test-kernel', 'changxing60', lambda root: calls.append(root))
        self.assertEqual(calls, ['test-kernel'])
        with self.assertRaises(ValueError):
            apply(Path('unused'), board='K1', m8_revision_compat=True)

    def test_k1_keeps_stock_gate_voltage_and_current(self):
        adapter = runpy.run_path(str(HERE.parent / 'k1/charger.py'))['apply']
        source = generated(lambda root: prepare(root, 'k1', adapter))
        self.assertIn('if (val != 0x12 || client->addr != 0x6b)', source)
        self.assertIn('"K1-0x12"', source)
        self.assertNotIn('chip_rev', source)
        self.assertIn('clamp_val(vol, 3856, 4380)', source)

    def test_real_41s_chain_keeps_its_0x1a_gate(self):
        adapter = runpy.run_path(str(HERE.parent / 'yuanhang41s/charger.py'))['apply']
        def chain(root):
            prepare(root, 'yuanhang41s')
            adapter(root)
        source = generated(chain)
        self.assertIn('client->addr = 0x1a;', source)
        self.assertIn('if ((val >> 3) != 0 || client->addr != 0x1a)', source)
        self.assertIn('"41S-SGM41513"', source)
        self.assertNotIn('chip_rev', source)
        self.assertNotIn('val != 0x11 && val != 0x12', source)
        self.assertIn('yh41s_charge_code(cur / 1000)', source)

    def test_otg_and_voltage_functions_remain_byte_identical(self):
        old = generated(lambda root: apply(root))
        new = generated(lambda root: prepare(root, 'm8'))
        for name in ('enable_otg', 'disable_otg', 'otg_work',
                     'register_vbus_regulator', 'set_limit_current',
                     'get_termina_vol', 'set_termina_vol', 'set_vindpm'):
            full = 'bq2560x_charger_' + name
            self.assertEqual(function(new, full), function(old, full), name)

    @unittest.skipIf(os.name == 'nt', 'Native POSIX C compiler required')
    def test_actual_revision_setters_and_getters(self):
        source = generated(lambda root: prepare(root, 'm8'))
        code = r'''
#include <stdint.h>
#include <errno.h>
#include <assert.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BQ2560X_REG_2 2
#define BQ2560X_REG_ICHG_MASK 63
#define min(a,b) ((a)<(b)?(a):(b))
struct bq2560x_charger_info {u8 chip_rev,reg;int error;};
static int bq2560x_read(struct bq2560x_charger_info *i,int a,u8 *v)
{(void)a;if(i->error)return -EIO;*v=i->reg;return 0;}
static int bq2560x_update_bits(struct bq2560x_charger_info *i,int a,u8 m,u8 v)
{(void)a;i->reg=(i->reg & ~m)|(v & m);return 0;}
'''
        code += function(source, 'bq2560x_charger_set_current')
        code += function(source, 'bq2560x_charger_get_current')
        code += r'''
int main(void) {
 struct bq2560x_charger_info i={.chip_rev=0x11,.reg=0xc0};u32 current=0;
 assert(!bq2560x_charger_set_current(&i,500000)&&i.reg==0xc8);
 assert(!bq2560x_charger_get_current(&i,&current)&&current==480000);
 assert(!bq2560x_charger_set_current(&i,3000000)&&(i.reg&63)==50);
 assert(!bq2560x_charger_get_current(&i,&current)&&current==3000000);
 assert(!bq2560x_charger_set_current(&i,4000000));
 assert(!bq2560x_charger_get_current(&i,&current)&&current==3000000);
 i.chip_rev=0x12;
 assert(!bq2560x_charger_set_current(&i,500000)&&(i.reg&63)==5);
 assert(!bq2560x_charger_get_current(&i,&current)&&current==450000);
 assert(!bq2560x_charger_set_current(&i,3047000)&&(i.reg&63)==53);
 assert(!bq2560x_charger_get_current(&i,&current)&&current==3047000);
 i.error=1;current=123;
 assert(bq2560x_charger_get_current(&i,&current)==-EIO&&current==123);
 return 0;
}
'''
        compile_run(code)


if __name__ == '__main__':
    unittest.main()
