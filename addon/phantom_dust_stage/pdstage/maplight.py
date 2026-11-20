"""Map lighting and fog: the stage's "mapLight" script (SSB, .dat header 0xD0).

The script is a flat list of native calls. Each argument is pushed as an int (word (v << 16) | 0x0E) or as raw
32 bits (word (low 16 bits << 16) | 0x0F, then the 32-bit value: a float or a packed 0x00RRGGBB colour). A call
is the word (id << 16) | (argument count << 8) | 0x01; 0x00000005 returns. The function table has one entry,
"maplight", at word 8 (right after the 0x20-byte header).

Calls (the game keeps four light sets of 0x58 bytes at 0x1403e8a40; set 0 = stage, 1 = characters and objects,
2 and 3 = the far models (background / sky), picked by FUN_140199970 while drawing):
  2000(ax, ay, az, dx, dy, dz, diffuse, diffuse2, ambient, set)   ambient axis, light direction, three colours
  2002(a, b, fog colour, mode, set)   mode 0 = off, 1/2 = exponential (density a), 3 = linear (start b, end a)
                                      (the PC version ignores fog: no render-state case for it)
  2005(range, x, y, z, colour, slot 0..2, set)   point light (range 0 = unused)
  2001(0, colour)   2003(scale, 0)
Distances are game units (10 per metre in the add-on's default scale).
"""
import struct

H_SCRIPT = 0xD0                 # stage .dat header: map-light script offset (0xD0 + 4 * variant)
VARIANT_SLOTS = 8

SET_LIGHT, SET_FOG, SET_POINT, GLOBAL_COLOUR, GLOBAL_SCALE = 0x2000, 0x2002, 0x2005, 0x2001, 0x2003
FOG_OFF, FOG_EXP, FOG_LINEAR = 0, 2, 3
SET_NAMES = ('stage', 'characters', 'far 1', 'far 2')


def f2u(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]


def u2f(u):
    return struct.unpack('<f', struct.pack('<I', u))[0]


def parse(s):
    """SSB bytes -> dict(header=bytes, name=(t1, t2), calls=[(id, [(kind, value)])]); kind 'i' or 'f' (raw bits)."""
    hsize, ftab, spool = struct.unpack_from('<3I', s, 0)
    t1, t2, start = struct.unpack_from('<3I', s, ftab)
    words = struct.unpack_from('<%dI' % ((ftab - hsize) // 4), s, hsize)
    calls, stack, i = [], [], start - hsize // 4
    while i < len(words):
        w = words[i]
        op = w & 0xFF
        if w & 0xFFFF == 0x0F:
            stack.append(('f', words[i + 1]))
            i += 2
            continue
        if w & 0xFFFF == 0x0E:
            stack.append(('i', w >> 16))
        elif op == 0x01:
            n = (w >> 8) & 0xFF
            calls.append((w >> 16, stack[len(stack) - n:]))
            del stack[len(stack) - n:]
        elif w == 0x05:
            break
        else:
            raise ValueError('unknown map-light instruction %08x at word %d' % (w, i))
        i += 1
    return dict(header=bytes(s[:hsize]), name=(t1, t2), calls=calls)


def build(script):
    """Inverse of parse()."""
    code = []
    for cid, args in script['calls']:
        for kind, v in args:
            if kind == 'i':
                code.append((v & 0xFFFF) << 16 | 0x0E)
            else:
                code += [(v & 0xFFFF) << 16 | 0x0F, v]
        code.append(cid << 16 | len(args) << 8 | 0x01)
    code.append(0x05)
    hdr = bytearray(script['header'])
    hsize = len(hdr)
    ftab = hsize + 4 * len(code)
    spool = ftab + 12
    struct.pack_into('<4I', hdr, 0, hsize, ftab, spool, spool)
    return bytes(hdr) + struct.pack('<%dI' % len(code), *code) + struct.pack('<3I', *script['name'], hsize // 4)


def script_of(dat_bytes, variant=0):
    off = struct.unpack_from('<I', dat_bytes, H_SCRIPT + 4 * variant)[0]
    if off == 0xFFFFFFFF or off + 8 > len(dat_bytes):
        return None
    s = dat_bytes[off:]
    ftab = struct.unpack_from('<I', s, 4)[0]
    return parse(s[:ftab + 12])


# ---- readable form ---------------------------------------------------------------------------------------------

def _num(a):
    kind, v = a
    return float(v) if kind == 'i' else u2f(v)


def _colour(a):
    v = a[1]
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def describe(script):
    """-> dict(sets=[...4 dicts...], colour=(r,g,b) or None, scale=float or None)."""
    sets = [dict(points=[None, None, None]) for _ in range(4)]
    out = dict(sets=sets, colour=None, scale=None)
    for cid, args in script['calls']:
        if cid == SET_LIGHT and len(args) == 10:
            s = sets[args[9][1]]
            s['axis'] = tuple(_num(a) for a in args[0:3])
            s['direction'] = tuple(_num(a) for a in args[3:6])
            s['diffuse'], s['diffuse2'], s['ambient'] = (_colour(a) for a in args[6:9])
        elif cid == SET_FOG and len(args) == 5:
            s = sets[args[4][1]]
            s['fog_mode'] = args[3][1]
            s['fog_colour'] = _colour(args[2])
            a, b = _num(args[0]), _num(args[1])
            s['fog_density'], s['fog_start'], s['fog_end'] = a, b, a
        elif cid == SET_POINT and len(args) == 7:
            sets[args[6][1]]['points'][args[5][1]] = dict(range=_num(args[0]), pos=tuple(_num(a) for a in args[1:4]),
                                                          colour=_colour(args[4]))
        elif cid == GLOBAL_COLOUR and len(args) == 2:
            out['colour'] = _colour(args[1])
        elif cid == GLOBAL_SCALE and len(args) == 2:
            out['scale'] = _num(args[0])
    return out


# ---- edits -----------------------------------------------------------------------------------------------------

def _f(x):
    return ('f', f2u(float(x)))


def _c(rgb):
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return ('f', r << 16 | g << 8 | b)


def set_fog(script, light_set, mode, colour=(0, 0, 0), start=0.0, end=0.0, density=0.0):
    """Replace the fog call of one light set (game units)."""
    if mode == FOG_LINEAR:
        a, b = end, start
    elif mode == FOG_EXP:
        a, b = density, 0.0
    else:
        a, b, colour = 0.0, 0.0, (0, 0, 0)
    args = [_f(a), _f(b), _c(colour), ('i', mode), ('i', light_set)]
    _replace(script, SET_FOG, light_set, 4, args)


def set_light(script, light_set, direction, diffuse, ambient, diffuse2=None, axis=None):
    """Replace the light call of one set. direction: unit vector in game space, as stored (the direction the
    light travels, e.g. (x, -1, z) for light from above); axis: the ambient up axis (default from the base)."""
    old = describe(script)['sets'][light_set]
    axis = axis or old.get('axis', (0.0, 1.0, 0.0))
    diffuse2 = diffuse2 if diffuse2 is not None else old.get('diffuse2', (0, 0, 0))
    args = [_f(x) for x in axis] + [_f(x) for x in direction] + [_c(diffuse), _c(diffuse2), _c(ambient), ('i', light_set)]
    _replace(script, SET_LIGHT, light_set, 9, args)


def _replace(script, cid, light_set, set_arg, args):
    for i, (c, a) in enumerate(script['calls']):
        if c == cid and len(a) > set_arg and a[set_arg] == ('i', light_set):
            script['calls'][i] = (cid, args)
            return
    raise ValueError('light set %d has no %04x call' % (light_set, cid))


def write(dat_bytes, script):
    """Append the script to the .dat and point every map-light slot that was in use at it."""
    b = bytearray(dat_bytes)
    while len(b) % 4:
        b.append(0)
    off = len(b)
    b += build(script)
    used = [v for v in range(VARIANT_SLOTS) if struct.unpack_from('<I', b, H_SCRIPT + 4 * v)[0] != 0xFFFFFFFF]
    for v in used or [0]:
        struct.pack_into('<I', b, H_SCRIPT + 4 * v, off)
    struct.pack_into('<I', b, 0x138, len(b))
    return bytes(b)
