"""Translate vendor composite dividers to the upstream signed-offset API.

Vendor composite.h fixes offset=4 and div.c uses common.reg - offset.
The upstream helper uses common.reg + offset: retaining +4 addresses the
next clock's control word. Preserve the register address with signed -4.
"""
import re


def translate_legacy_offsets(source):
    def divider(match):
        fields = [field.strip() for field in match.group(1).split(',')]
        if len(fields) != 9:
            raise ValueError('Unexpected legacy composite clock arguments')
        fields.insert(6, '-0x4')
        return 'SPRD_COMP_CLK_DATA_OFFSET(' + ', '.join(fields) + ')'
    return re.sub(r'SPRD_COMP_CLK_DATA_OFFSET\(([^;]+?)\)', divider, source)
