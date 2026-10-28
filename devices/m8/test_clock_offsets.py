"""Verify every imported clock retains its factory divider register address."""
from pathlib import Path
import re
import runpy
import unittest

HERE = Path(__file__).resolve().parent
translate = runpy.run_path(str(HERE.parent/'common/clock-offsets.py'))['translate_legacy_offsets']


class Offsets(unittest.TestCase):
    def test_all_factory_clock_divider_addresses_are_preserved(self):
        original=(HERE/'port/drivers/clk/sprd/ums9620-clk.c').read_text()
        pattern=r'SPRD_COMP_CLK_DATA_OFFSET\(([^;]+?)\)'
        before=re.findall(pattern,original)
        after=re.findall(pattern,translate(original))
        self.assertGreater(len(before),20)
        self.assertEqual(len(before),len(after))
        for old,new in zip(before,after):
            old=[x.strip() for x in old.split(',')]
            new=[x.strip() for x in new.split(',')]
            self.assertEqual(old,new[:6]+new[7:])
            register=int(old[3],0)
            offset=int(new[6],0)
            self.assertEqual(register-4,register+offset,old[0])
        dpi=next(x for x in after if x.startswith('dispc0_dpi,'))
        fields=[x.strip() for x in dpi.split(',')]
        self.assertEqual(int(fields[3],0)+int(fields[6],0),0x78)

    def test_new_api_or_malformed_inputs_are_not_translated_twice(self):
        with self.assertRaises(ValueError):
            translate('SPRD_COMP_CLK_DATA_OFFSET(a,b,c,0x7c,0,3,-4,0,3,0)')
        self.assertEqual(translate('ordinary clock definition'),'ordinary clock definition')


if __name__=='__main__':unittest.main()
