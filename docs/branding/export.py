#!/usr/bin/env python3
"""Lossless PNG container export: preserve every pixel, recompress IDAT only."""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def chunks(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8
    while offset < len(data):
        size = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        assert zlib.crc32(kind + payload) == struct.unpack('>I', data[offset + 8 + size:offset + 12 + size])[0]
        yield kind, payload
        offset += 12 + size
    assert offset == len(data)


def chunk(kind, data):
    return struct.pack('>I',len(data)) + kind + data + struct.pack('>I',zlib.crc32(kind + data))


def export(name):
    original = list(chunks((ROOT / 'source' / (name + '.original.png')).read_bytes()))
    # Recompression changes the byte-level C2PA binding. Preserve the signed
    # original separately; do not carry its stale caBX manifest into the export.
    assert all(kind in (b'IHDR',b'IDAT',b'IEND',b'caBX') for kind, _ in original)
    header = next(data for kind, data in original if kind == b'IHDR')
    raw = zlib.decompress(b''.join(data for kind, data in original if kind == b'IDAT'))
    encoded = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',header) + chunk(b'IDAT',zlib.compress(raw,9)) + chunk(b'IEND',b'')
    decoded = list(chunks(encoded))
    assert zlib.decompress(b''.join(data for kind, data in decoded if kind == b'IDAT')) == raw
    assert next(data for kind, data in decoded if kind == b'IHDR') == header
    path = ROOT / (name + '.png')
    path.write_bytes(encoded)
    print(path.name, struct.unpack('>II', header[:8]), len(encoded), 'bytes; pixel data unchanged')
    return path


if __name__ == '__main__':
    export('solartt-avatar')
    preview = export('solartt-social-preview')
    assert preview.stat().st_size < 1_000_000, 'Social preview exceeds GitHub upload limit'
