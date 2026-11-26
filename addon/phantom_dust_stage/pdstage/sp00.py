"""SP00: the stage's sprite types (header word 0x9C), read and written.

What the game does with it (Xbox XBE `Stage_ParseSp00` 0xE0DB0 and `Stage_LoadSp00Animations` 0xE0F30; the 2017 PC
port's `sub_140205790` is the same loop):

- Section: tag `SP00`, u32 list count, u32 1 (not read: the parser starts at +12), then `count` frame lists (u32
  frame count, then 32-byte frames), then u32 name bytes, u32 entry count, the NUL-terminated texture names, the
  entries (5 x u32) and one more 20-byte entry the parser itself zeroes (the table's end: written as zeros, it must
  be there or the parser zeroes the next section's first 20 bytes).
- Entry: `name` (index of a name in the name list: the parser skips that many strings; "NOUSE" = none), `list`
  (frame list index), `capacity` (the loader reserves capacity * 128 bytes, four 32-byte vertices per quad, from a
  512 KiB pool on the Xbox and 1 MiB on the PC: how many quads the sprite type can have alive), `frames` (how many
  frames of the list the sprite plays), `blend` (selects a pair of render-state routines at 0x2CA4C0: begin / end).
- An entry is dropped (its sprite slot stays empty) when its name is NOUSE, its capacity is 0, or no texture of the
  stage model (.alr) has that name (`sub_14CE50`: the name up to its '.', as two base-40 words, so case-insensitive
  and at most 12 characters).
- Frame: quad corners (left, top, right, bottom; scaled by 127 for the vertex data, 0x15EE30) and the texture
  rectangle (u0, v0, u1, v1).
- The stage's entries follow the shared table of Map/st00 in one sprite numbering; effect records name a sprite by
  that number (the entry index here is the stage part of it).
"""
import struct

NONE = 0xFFFFFFFF
H_SP00 = 0x9C
FRAME = struct.Struct('<8f')
ENTRY = struct.Struct('<5I')

# the render-state pairs of 0x2CA4C0 (begin, end), Xbox code read in IDA. Kinds 1-5 set the blend word of
# 0x14BDE0: bits 8-11 source factor, 12-15 destination factor (table 0x2A40A8), bits 5-7 the operation (0x2A4084,
# 0 = add); every kind writes no depth and (1-5) alpha-tests "not 0"
BLEND = {
    0: ('CUTOUT', 'Cut-out: no blending, alpha test greater than 0xFE (0xE1710)'),
    1: ('ALPHA', 'Alpha blend: source alpha, inverse source alpha (word 0x5401, 0xE1740)'),
    2: ('ADD', 'Additive: one, one (word 0x1101, 0xE1760)'),
    3: ('DARKEN', 'Darken: zero, inverse source alpha (word 0x5001, 0xE1780)'),
    4: ('SCREEN', 'Inverse destination colour, inverse source colour (word 0x3901, 0xE17A0)'),
    5: ('MODULATE_ADD', 'Destination colour, one (word 0x1801, 0xE17C0)'),
    6: ('KEEP', 'Depth not written, the blend state left as it is (0xE17E0)'),
    7: ('KIND_7', 'Routine 0x14BED0 only (0xE17F0); not used by any stage file'),
}


def read(b):
    """dict(lists=[[frame (8 floats)]], entries=[dict(name, list, capacity, frames, blend)]), or None.
    name is the texture name as written ('NOUSE' kept)."""
    o = struct.unpack_from('<I', b, H_SP00)[0]
    if o == NONE or bytes(b[o:o + 4]) != b'SP00':
        return None
    n_lists = struct.unpack_from('<I', b, o + 4)[0]
    p, lists = o + 12, []
    for _ in range(n_lists):
        n = struct.unpack_from('<I', b, p)[0]
        p += 4
        lists.append([FRAME.unpack_from(b, p + 32 * k) for k in range(n)])
        p += 32 * n
    nb, count = struct.unpack_from('<II', b, p)
    p += 8
    names = bytes(b[p:p + nb]).split(b'\0')
    p += nb
    entries = []
    for i in range(count):
        ni, li, cap, nf, bl = ENTRY.unpack_from(b, p + 20 * i)
        entries.append(dict(name=names[ni].decode('latin-1') if ni < len(names) else 'NOUSE', list=li,
                            capacity=cap, frames=nf, blend=bl))
    return dict(lists=lists, entries=entries, offset=o, end=p + 20 * (count + 1))


def active(entry, texture_names=None):
    """True when the game makes a sprite of this entry (see the module notes)."""
    if entry['name'] == 'NOUSE' or not entry['capacity']:
        return False
    if texture_names is not None:
        return game_name(entry['name']) in texture_names
    return True


def game_name(name):
    """The texture name the loader looks up: up to the '.', lower case, 12 characters."""
    return name.split('.')[0].lower()[:12]


def build(sprites, count=None):
    """SP00 bytes from sprites: {number: dict(texture, capacity, blend, frames=[8 floats], played=frames the type
    plays (default: all))}. Numbers not given are
    NOUSE entries. Identical frame lists are written once."""
    count = max(sprites) + 1 if sprites and count is None else (count or 0)
    lists, list_index = [], {}
    names = []
    rows = []
    for i in range(count):
        s = sprites.get(i)
        if s is None:
            names.append('NOUSE')
            rows.append((i, 0, 0, 0, 0))
            continue
        key = tuple(tuple(float(x) for x in f) for f in s['frames'])
        if key not in list_index:
            list_index[key] = len(lists)
            lists.append(key)
        names.append(s['texture'])
        rows.append((i, list_index[key], int(s['capacity']), int(s.get('played', len(key))), int(s['blend'])))
    if not lists:
        lists.append(((-5.0, 5.0, 5.0, -5.0, 0.0, 0.0, 1.0, 1.0),))      # the parser needs one list to point at
    out = bytearray(b'SP00' + struct.pack('<II', len(lists), 1))
    for fl in lists:
        out += struct.pack('<I', len(fl)) + b''.join(FRAME.pack(*f) for f in fl)
    name_bytes = b''.join(n.encode('latin-1') + b'\0' for n in names)
    out += struct.pack('<II', len(name_bytes), count) + name_bytes
    out += b''.join(ENTRY.pack(*r) for r in rows) + bytes(20)
    return bytes(out)


def put(b, section):
    """New .dat bytes with `section` appended and header word 0x9C pointing at it (the old one is left for
    datfile.compact to remove)."""
    buf = bytearray(b)
    off = len(buf)
    buf += section
    struct.pack_into('<I', buf, H_SP00, off)
    struct.pack_into('<I', buf, 0x138, len(buf))
    return bytes(buf)
