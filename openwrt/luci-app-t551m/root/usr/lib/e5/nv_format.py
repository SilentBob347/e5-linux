"""Read-only fixed-NV/IMEI parser, based on the user's NVTool/NSA workspace.
No record rewriting, generation changes or identity filtering is performed.
"""
import array
import hashlib
from pathlib import Path
import struct
import sys

# Identity/signing items listed separately from CALINVITEM in the supplied
# nvmerge.cfg. Used only to classify displayed differences, never to filter
# full-file writeback.
PROTECTED = frozenset((0x0005, 0x0179, 0x0186, 0x01e4, 0x01a6, 0x01a3,
                       0x01a4, 0x01f0, 0x01f1, 0x01f2, 0x01f4, 0x07e4,
                       0x091b, 0x09f4, 0x0a85))


class FormatError(ValueError):
    pass


def checksum(data, bits=64):
    words = array.array('H'); words.frombytes(data)
    if sys.byteorder != 'little': words.byteswap()
    total = sum(words)
    if bits == 32: total &= 0xffffffff
    while total >> 16: total = (total & 0xffff) + (total >> 16)
    return total ^ 0xffff


def decode_imei(data):
    if len(data) != 8 or not any(data) or all(n == 0xff for n in data): return None
    digits = ''.join(f'{n & 15:X}{n >> 4:X}' for n in data)
    return digits[1:] if digits[0] == 'A' and digits[1:].isdigit() else None


class FixedNV:
    def __init__(self, data):
        self.data = bytes(data)
        if len(data) < 524: raise FormatError('nv_layout_unsupported')
        magic, size, expected, version = struct.unpack_from('<4I', data)
        if magic != 0x4e56 or version != 101 or size % 2 or not 8 <= size <= len(data)-512:
            raise FormatError('nv_layout_unsupported')
        self.size = size; self.payload = memoryview(self.data)[512:512+size]
        modes = [bits for bits in (64, 32) if checksum(self.payload, bits) == expected]
        if not modes: raise FormatError('nv_invalid_checksum')
        self.modes = modes
        self.has_sha256 = any(self.data[16:48])
        if self.has_sha256 and self.data[16:48] != hashlib.sha256(self.payload).digest():
            raise FormatError('nv_header_integrity_unknown')
        self.bits = modes[0]; self.generation = struct.unpack_from('<I', self.payload)[0]
        self.items = {}; self.regions = {}; pos = 4; boundaries = set(); index = None
        while pos + 4 <= size:
            ident, length = struct.unpack_from('<HH', self.payload, pos)
            boundaries.add(pos)
            if ident == 0xffff: break
            end = pos+4+((length+3)&~3)
            if end > size or ident in self.items and ident != 0xfffe:
                raise FormatError('nv_layout_unsupported')
            if ident == 0:
                value = self.payload[pos+4:pos+4+length]
                if pos != 4 or length != 56 or bytes(value[:4]) != b'INDX' or struct.unpack_from('<H', value, 6)[0] != 2:
                    raise FormatError('nv_layout_unsupported')
                if bytes(value[8:12]) != b'PSCP' or bytes(value[32:35]) != b'PHY':
                    raise FormatError('nv_layout_unsupported')
                ps, nps, phy, nphy = (struct.unpack_from('<I', value, n)[0] for n in (24, 28, 48, 52))
                if ps != 64 or not ps < ps+nps <= phy < phy+nphy <= size:
                    raise FormatError('nv_layout_unsupported')
                index = (ps, ps+nps, phy, phy+nphy)
            elif ident != 0xfffe:
                if not length: raise FormatError('nv_layout_unsupported')
                self.items[ident] = (512+pos+4, length)
                if index:
                    if index[0] <= pos and end <= index[1]: region = 'protocol'
                    elif index[2] <= pos and end <= index[3]: region = 'radio'
                    elif pos >= index[3]: region = 'extension'
                    else: raise FormatError('nv_layout_unsupported')
                    self.regions[ident] = region
            pos = end
        else: raise FormatError('nv_layout_unsupported')
        if index is None or not set(index).issubset(boundaries) or pos < index[3]:
            raise FormatError('nv_layout_unsupported')
        if 5 not in self.items or self.items[5][1] != 8:
            raise FormatError('nv_identity_unavailable')

    @classmethod
    def read(cls, path):
        return cls(Path(path).read_bytes())

    def value(self, ident):
        offset, size = self.items[ident]
        return self.data[offset:offset+size]

    def imeis(self):
        return {name: decode_imei(self.value(ident)) if ident in self.items else None
                for name, ident in (('sim1', 5), ('sim2', 0x179))}

    def compatible(self, other):
        if self.size != other.size or self.items.keys() != other.items.keys() or self.regions != other.regions:
            raise FormatError('nv_layout_mismatch')
        if any(self.items[n][1] != other.items[n][1] for n in self.items):
            raise FormatError('nv_layout_mismatch')

    def difference(self, other):
        self.compatible(other)
        changed = [n for n in self.items if n not in PROTECTED and self.value(n) != other.value(n)]
        return {'items': len(changed), 'bytes': sum(sum(a != b for a, b in zip(self.value(n), other.value(n))) for n in changed),
                'identity_items': sum(self.value(n) != other.value(n) for n in self.items if n in PROTECTED),
                'protocol_items': sum(self.regions[n] == 'protocol' for n in changed),
                'radio_items': sum(self.regions[n] == 'radio' for n in changed)}

