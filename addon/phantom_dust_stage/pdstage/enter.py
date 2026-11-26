"""The stage's enter chunk stream (header word 0xFC + 4 * k, else 0xFC): read and written.

Who reads it (both executables alike):
- Battle maps: the stream of word 0xFC + 4 * (stage / 10), else 0xFC, goes to the battle light object, which clears
  its light objects and plays the chunks from light object 0 (Xbox `Stage_PlayEnterChunks` 0xE03B0: the pointer is
  passed in EAX to `sub_8A0C0` at 0xE0567, which Hex-Rays drops; PC `sub_140204860` -> `sub_14019A020`). Every battle
  map of the game holds an empty stream (one end chunk {0, 8}) or none, so nothing is placed.
- The town (stage number % 10 == 9): word 0xFC through the ALR chunk runner (0x14CF10) with light objects numbered
  from 32, then the area's own list (`Stage_PlayVariantChunks` 0xE0610).

The only chunk any stage file puts there is id 9, a light list (read by 0x14D290): u32 9, u32 size, u32 count, then
40-byte records:
  +0  u32 colour 0x00RRGGBB      +4 u8 kind (1 directional, 2 and 3 point, 5 hemisphere; others clear the light)
  +5  u8 light object index (used when flag bit 1 is set; else the next object from the base)
  +6  u8 flags: 0x02 use +5, 0x08 / 0x10 masks 2 / 4 of the characters' light choice (0x14FF50); other bits unread
  +7  u8 not read
  +8  f32[3] vector (a directional light's direction, a hemisphere's axis)
  +20 f32 intensity              +24 f32[3] position (point lights)
  +36 f32 (kind 1 only: copied to the light object's +0x60; points get 1.0 there)
"""
import struct

NONE = 0xFFFFFFFF
H_ENTER = 0xFC
LIGHT_LIST = 9
RECORD = struct.Struct('<IBBBB3ff3ff')
END = struct.pack('<II', 0, 8)


def stream_offset(b, k=0, field=None):
    o = struct.unpack_from('<I', b, H_ENTER + 4 * k if field is None else field)[0]
    return None if o == NONE else o


def read(b, k=0, base=32, field=None):
    """dict(lights=[dict(index, kind, colour (r, g, b bytes), vector, intensity, position, mask, value_36)],
    other=[chunk ids that are not light lists], present=bool). `index`: the light object the record fills (explicit
    or from `base` on, as the game counts). field: the header word holding the stream (the town's area files: 0x18)."""
    o = stream_offset(b, k, field)
    out = dict(lights=[], other=[], present=o is not None)
    if o is None:
        return out
    j, nxt = o, base
    while j + 8 <= len(b):
        cid, size = struct.unpack_from('<II', b, j)
        if cid == 0:
            break
        if cid == LIGHT_LIST:
            n = struct.unpack_from('<I', b, j + 8)[0]
            for i in range(n):
                col, kind, target, flags, _b7, vx, vy, vz, inten, px, py, pz, v36 = RECORD.unpack_from(
                    b, j + 12 + 40 * i)
                if flags & 2:
                    index = target
                else:
                    index, nxt = nxt, nxt + 1
                out['lights'].append(dict(index=index, kind=kind, colour=((col >> 16) & 255, (col >> 8) & 255,
                                                                          col & 255),
                                          vector=(vx, vy, vz), intensity=inten, position=(px, py, pz),
                                          mask=(4 if flags & 0x10 else 0) | (2 if flags & 8 else 0),
                                          value_36=v36))
        else:
            out['other'].append(cid)
        if size < 8:
            break
        j += size
    return out


def build(lights):
    """Stream bytes: one light list (every record with its light object index explicit) and the end chunk; an empty
    stream when there are no lights."""
    if not lights:
        return END
    recs = bytearray()
    for L in lights:
        r, g, bl = (int(max(0, min(255, round(c)))) for c in L['colour'])
        flags = 2 | (0x10 if L['mask'] & 4 else 0) | (8 if L['mask'] & 2 else 0)
        recs += RECORD.pack((r << 16) | (g << 8) | bl, int(L['kind']), int(L['index']), flags, 0,
                            *L['vector'], float(L['intensity']), *L['position'],
                            float(L.get('value_36', 0.0)) if int(L['kind']) == 1 else 0.0)
    return struct.pack('<III', LIGHT_LIST, 12 + len(recs), len(lights)) + bytes(recs) + END


def put(b, stream, k=0):
    """New .dat bytes with `stream` appended and word 0xFC + 4k pointing at it (the old stream is left for
    datfile.compact to remove)."""
    buf = bytearray(b)
    off = len(buf)
    buf += stream
    struct.pack_into('<I', buf, H_ENTER + 4 * k, off)
    struct.pack_into('<I', buf, 0x138, len(buf))
    return bytes(buf)
