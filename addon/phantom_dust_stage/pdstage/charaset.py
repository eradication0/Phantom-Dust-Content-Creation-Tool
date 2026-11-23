"""setup\\charaset\\charaset.dat and charaset_en.dat: one 0x4C record per model (Tinkerer_Red's reference, Part B
section 2). Header: u32 file size, u32 count (47), u32 string-pool offset, u32 0; records from +16; strings
(UTF-8, NUL-terminated) in the pool, record string fields are pool offsets.

Fields used here: +0x00 model folder (pc00a...), +0x04 name, +0x0C capsule height, +0x0E capsule width, +0x10 hit
radius, +0x12 hit centre height (all x 0.1 game units: the body collider and the hit volume), +0x36 movement skill
(750 jump, 751 cartwheel / dash), +0x3C voice bank file name (BattleVo_<Name>.bin, the language suffix is added
by the game; NPC records hold an unused out-of-pool value), +0x40 six exmot clip lengths in frames.
The Japanese file is used when the game language is Japanese, else the _en file; their numbers are equal, only
the strings differ, so both are edited the same way.
"""
import struct

RECORD = 0x4C
JUMP, CARTWHEEL = 750, 751
FILES = ('charaset_en.dat', 'charaset.dat')


def _pool(b):
    _size, n, pool, _z = struct.unpack_from('<4I', b, 0)
    return n, pool


def string(b, off):
    _n, pool = _pool(b)
    if off >= len(b) - pool:
        return None
    end = b.index(b'\0', pool + off)
    return b[pool + off:end].decode('utf-8', 'replace')


def records(b):
    n, _pool_ = _pool(b)
    out = []
    for i in range(n):
        r = 16 + i * RECORD
        model, name, _disp = struct.unpack_from('<3I', b, r)
        voice = struct.unpack_from('<I', b, r + 0x3C)[0]
        out.append(dict(index=i, model=string(b, model), name=string(b, name), height=struct.unpack_from('<h', b, r + 0x0C)[0],
                        move=struct.unpack_from('<h', b, r + 0x36)[0], voice_off=voice, voice=string(b, voice),
                        exmot=list(struct.unpack_from('<6h', b, r + 0x40))))
    return out


def voices(b):
    """{voice file name: pool offset} of every voice bank the file names."""
    return {r['voice']: r['voice_off'] for r in records(b) if r['voice']}


def record_of(b, model):
    """The first record of a model folder name (pc00a ...)."""
    return next((r for r in records(b) if r['model'] == model), None)


def hitbox(b, model):
    """(capsule height, capsule width, hit radius, hit centre height) of a model's record, in tenths of a game
    unit, or None."""
    r = record_of(b, model)
    return None if r is None else struct.unpack_from('<4h', b, 16 + r['index'] * RECORD + 0x0C)


def patch(b, model, move=None, voice=None, exmot=None, height=None, box=None):
    """New file bytes with the model's record changed. voice: a file name another record already uses (its pool
    offset is reused, so the pool does not change)."""
    out = bytearray(b)
    r = record_of(b, model)
    if r is None:
        raise KeyError('%s has no record in charaset' % model)
    at = 16 + r['index'] * RECORD
    if move is not None:
        struct.pack_into('<h', out, at + 0x36, move)
    if voice is not None:
        offs = voices(b)
        if voice not in offs:
            raise KeyError('no record uses the voice bank %s' % voice)
        struct.pack_into('<I', out, at + 0x3C, offs[voice])
    if exmot is not None:
        struct.pack_into('<6h', out, at + 0x40, *[int(x) for x in exmot])
    if height is not None:
        struct.pack_into('<h', out, at + 0x0C, int(height))
    if box is not None:
        struct.pack_into('<4h', out, at + 0x0C, *[int(x) for x in box])
    return bytes(out)
