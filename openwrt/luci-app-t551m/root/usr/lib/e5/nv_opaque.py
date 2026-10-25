"""Write eligibility for NV without a standard VN checksum wrapper.

Delta block framing follows the user's reference_nv_tool.py/compare_endc.py.
Only values within the original board's same block/record layout may change.
Unknown calinv mutations are not promoted to validated data by hashing them.
"""
import struct


def delta_layout(path):
    data = path.read_bytes(); pos = 0; blocks = []
    while pos < len(data) and data[pos] != 0:
        if pos+28 > len(data): raise ValueError('delta header')
        field = data[pos:pos+20]; end = field.find(b'\0')
        if end <= 0 or any(field[end:]): raise ValueError('delta name')
        name = field[:end]
        if any(not (48 <= n <= 57 or 65 <= n <= 90 or 97 <= n <= 122 or n in (45, 95)) for n in name):
            raise ValueError('delta name')
        version, size = struct.unpack_from('<HI', data, pos+20)
        # The stock dumps use more than one header flag/version. Preserve and
        # compare it with the original instead of assuming a constant value.
        if size < 28 or pos+size > len(data): raise ValueError('delta size')
        cursor = pos+26; stop = pos+size; records = []; terminated = False
        while cursor+2 <= stop:
            ident = struct.unpack_from('<H', data, cursor)[0]
            if ident == 0xffff:
                if cursor+2 != stop: raise ValueError('delta terminator')
                terminated = True; break
            if cursor+6 > stop: raise ValueError('delta record')
            ident, attr, length = struct.unpack_from('<3H', data, cursor)
            cursor += 6+length
            if cursor > stop: raise ValueError('delta record length')
            records.append((ident, attr, length))
        if not terminated: raise ValueError('delta terminator')
        blocks.append((name, version, tuple(records))); pos = stop
    if not blocks or any(data[pos:]): raise ValueError('delta padding')
    return tuple(blocks)


def eligibility(manager, state):
    import nv_persistence as nv
    devices = manager.map(); checks = {}; blocked = []
    for name in nv.NAMES:
        local = state['local'][name]['sha256']; original = state['source'][name]['sha256']
        if name.startswith(('nr_fixnv', 'nr_runtimenv')):
            checks[name] = 'vn-checksum'; continue
        if local == original:
            checks[name] = 'identical'; continue
        if local == state['origin'][name]:
            # This is still an exact snapshot of THIS unit's recorded original,
            # not a newly created opaque calibration blob without a validator.
            checks[name] = 'original-snapshot'; continue
        try:
            if name.startswith('nr_deltanv'):
                if delta_layout(manager.store/name) != delta_layout(devices[name]):
                    raise ValueError('delta board/record layout changed')
                checks[name] = 'delta-layout'
            else:
                # A checksum-bearing calinv is accepted only if the existing
                # original uses the same known container family too.
                nv.validate(devices[name], 'nr_fixnv1_a')
                nv.validate(manager.store/name, 'nr_fixnv1_a')
                checks[name] = 'vn-checksum'
        except (OSError, ValueError, nv.NVError):
            checks[name] = 'unverified'; blocked.append(name)
    return {'writeback_scope': [n for n in nv.NAMES if n not in blocked], 'writeback_checks': checks,
            'writeback_blocked': blocked,
            'writeback_reason': ''}
