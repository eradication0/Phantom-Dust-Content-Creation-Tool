"""Reader for stage files Assets/Data/Map/stNN.dat (battle maps).

Layouts were read from PDUWP.exe (FUN_140203720 and the collision functions) and confirmed
in game; see FORMATS.md. Story/event stages (st00, st09_0x) use a different header.
"""
import math
import re
import struct
from dataclasses import dataclass, field

NONE = 0xFFFFFFFF

# Header: u32 offsets from the start of the file (NONE = absent).
H_LAYOUT_SLOTS = 0x04    # 11 x u32
H_LAYOUT_COUNTS = 0x30   # 11 x u32
H_NAMES = 0x5C           # NM00
H_OBJECT_COUNT = 0x60    # a count, not an offset
H_OBJECTS = 0x90         # OB00, 0x38-byte entries
H_COLLISION = 0x94
H_EF00 = 0x98
H_SP00 = 0x9C
H_MD00 = 0xA0           # MD00 stage models list
H_OBJECT_SOUNDS = 0xF8  # 16 bytes per object (8 x u16, FFFF = none): [1] its hit/break sound, [2] its pieces' impact sound
H_FILE_SIZE = 0x138      # equals the file size in every map


def layout_kind(b):
    """'stage' (the 0x13C-byte ST00 header of the battle maps and st09), 'short' (st00.dat: ST00 with a 0x28-byte
    header and no tables; the game never loads it), 'area' (the town's st09_NN.dat, AR01..AR08) or None.
    Only 'stage' files have the collision, spawn, object and effect tables read here."""
    if bytes(b[:4]) == b'ST00':
        return 'short' if len(b) >= 8 and struct.unpack_from('<I', b, 4)[0] == 0x28 else 'stage'
    if bytes(b[:2]) == b'AR':
        return 'area'
    return None


def header(b):
    if b[:4] != b'ST00':
        raise ValueError('not a stage .dat (no ST00 magic)')
    u = lambda o: struct.unpack_from('<I', b, o)[0]
    opt = lambda v: None if v == NONE else v
    return dict(
        layout_slots=[opt(u(H_LAYOUT_SLOTS + 4 * i)) for i in range(11)],
        layout_counts=[opt(u(H_LAYOUT_COUNTS + 4 * i)) for i in range(11)],
        names=opt(u(H_NAMES)), object_count=u(H_OBJECT_COUNT), objects=opt(u(H_OBJECTS)),
        collision=opt(u(H_COLLISION)), ef00=opt(u(H_EF00)), sp00=opt(u(H_SP00)),
        raw=[u(4 + 4 * i) for i in range(39)],
    )


def section_tags(b):
    """4-character section tags (e.g. NM00, OB00, CP00) with their offsets."""
    return [(m.start(), m.group().decode()) for m in re.finditer(rb'(?:NM|O[A-E]|EF|SP|MD|CP)00', b)]


# ---------------------------------------------------------------- object placements (PS00/PS01...)

PLACEMENT_SIZE = 0x24      # s32 object id, u8, u8, u16, u32, f32 pos[3], f32 rot[3] (Esper-RE st00.h)


def placement_tables(b):
    """The layout slots' object placement tables: list of (slot, offset, count)."""
    out = []
    for i in range(11):
        off = struct.unpack_from('<I', b, H_LAYOUT_SLOTS + 4 * i)[0]
        cnt = struct.unpack_from('<I', b, H_LAYOUT_COUNTS + 4 * i)[0]
        if off != NONE and cnt != NONE:
            out.append((i, off, cnt))
    return out


def clear_placements(buf):
    """Remove the map's placed objects (props, stairs, debris...) by setting every placement count to 0.
    Returns how many placements were removed."""
    n = 0
    for i, _off, cnt in placement_tables(buf):
        struct.pack_into('<I', buf, H_LAYOUT_COUNTS + 4 * i, 0)
        n += cnt
    return n


# ---------------------------------------------------------------- effects (EF00 at header 0x98)

EFFECT_SIZE = 0x5C         # u8 kind, u8, u8, u8, then floats: position at +4, ... scale at +0x1C


def effects(b):
    """EF00 effect placements: list of dict(offset, kind, pos, scale)."""
    o = struct.unpack_from('<I', b, H_EF00)[0]
    if o == NONE or b[o:o + 4] != b'EF00':
        return []
    n = struct.unpack_from('<H', b, o + 4)[0]
    out = []
    for i in range(n):
        e = o + 8 + i * EFFECT_SIZE
        out.append(dict(offset=e, kind=b[e], pos=struct.unpack_from('<3f', b, e + 4),
                        scale=struct.unpack_from('<3f', b, e + 0x1C)))
    return out


def hide_effects_in(buf, lo, hi, drop=100000.0):
    """Move effects placed inside the box lo..hi (the old map's area) far below the map, so lamps, falling
    rubble and the like from the old map don't appear. Effects at exactly (0, 0, 0) (map-wide ones) and
    outside the box (background) are kept. Entries are not removed or reordered. Returns how many moved."""
    n = 0
    for e in effects(buf):
        p = e['pos']
        if p == (0.0, 0.0, 0.0):
            continue
        if all(lo[k] <= p[k] <= hi[k] for k in range(3)):
            struct.pack_into('<f', buf, e['offset'] + 8, p[1] - drop)
            n += 1
    return n


def clear_effects(buf):
    """Remove every EF00 effect placement (count set to 0). Returns how many there were."""
    o = struct.unpack_from('<I', buf, H_EF00)[0]
    if o == NONE or buf[o:o + 4] != b'EF00':
        return 0
    n = struct.unpack_from('<H', buf, o + 4)[0]
    struct.pack_into('<HH', buf, o + 4, 0, 0)
    return n


def collision_bounds(b):
    pts = [v for vl in collision(b)[1] for v in vl.verts]
    if not pts:
        return None
    return tuple(min(p[k] for p in pts) for k in range(3)), tuple(max(p[k] for p in pts) for k in range(3))


# ---------------------------------------------------------------- spawns and orbs (CP00)

ENTRY_SIZE = 0x50
ENTRY_MARK = 0x80100003


@dataclass
class Spawn:
    offset: int
    pos: tuple            # x, y, z (y up)
    yaw: float            # radians; the 3 orbs normally lie in front of this facing
    orbs: list            # 3 x (x, y, z)
    tail: tuple           # u32 x4, meaning unknown (usually 128, 3, 24, 0)
    flags: int            # u32, meaning unknown (000b641c / 000b664c)


def spawn_layouts(b):
    """CP00 sections: one list of Spawn per layout (usually 4 entries = 4 players)."""
    layouts = []
    for m in re.finditer(rb'CP00', b):
        o = m.start()
        hdr = struct.unpack_from('<I', b, o + 4)[0]
        size, count = hdr >> 16, hdr & 0xFFFF
        if size != count * ENTRY_SIZE:
            continue
        entries = []
        for i in range(count):
            e = o + 8 + i * ENTRY_SIZE
            if struct.unpack_from('<I', b, e + 0x10)[0] != ENTRY_MARK:
                raise ValueError('unexpected CP00 entry at %#x' % e)
            entries.append(Spawn(
                offset=e,
                pos=struct.unpack_from('<3f', b, e),
                yaw=struct.unpack_from('<f', b, e + 0x0C)[0],
                orbs=[struct.unpack_from('<3f', b, e + 0x14 + k * 12) for k in range(3)],
                tail=struct.unpack_from('<4I', b, e + 0x3C),
                flags=struct.unpack_from('<I', b, e + 0x4C)[0]))
        layouts.append(entries)
    return layouts


def write_spawn(buf, s):
    """Write a Spawn's position, yaw and orbs back in place (tail and flags untouched)."""
    struct.pack_into('<3f', buf, s.offset, *s.pos)
    struct.pack_into('<f', buf, s.offset + 0x0C, s.yaw)
    for k, ob in enumerate(s.orbs):
        struct.pack_into('<3f', buf, s.offset + 0x14 + k * 12, *ob)


# ---------------------------------------------------------------- collision

KIND_MESH = 3
KIND_VERTS = 8


@dataclass
class Record:
    offset: int
    type: int             # surface type; meaning mostly unknown
    kind: int             # 8 = vertex list, 3 = triangle chunk
    flags: int            # 0x03 in every map
    b3: int
    size: int             # bytes after the 12-byte header
    w8: int
    verts: list = field(default_factory=list)       # kind 8
    center: tuple = None                             # kind 1/3
    radius: float = None
    bbox_min: tuple = None
    bbox_max: tuple = None
    vlist: int = None                                # kind 3: index of the kind-8 record
    tris: list = field(default_factory=list)         # kind 3: (a, b, c, attr, normal)


def collision(b, base=None):
    """All collision records, plus the vertex lists in order. `base` reads a chain at another offset
    (e.g. an object's own collision); by default the stage collision from header 0x94."""
    if base is None:
        base = struct.unpack_from('<I', b, H_COLLISION)[0]
    if base == NONE:
        return [], []
    recs, vlists, o = [], [], base
    while b[o] != 0xFF:
        typ, kind, flags, b3, size, w8 = struct.unpack_from('<4B2I', b, o)
        r = Record(o, typ, kind, flags, b3, size, w8)
        if kind == KIND_VERTS:
            r.verts = [struct.unpack_from('<3f', b, o + 0xC + i * 12) for i in range(size // 12)]
            vlists.append(r)
        elif kind in (1, KIND_MESH):
            r.center = struct.unpack_from('<3f', b, o + 0x0C)
            r.radius = struct.unpack_from('<f', b, o + 0x18)[0]
            r.bbox_min = struct.unpack_from('<3f', b, o + 0x1C)
            r.bbox_max = struct.unpack_from('<3f', b, o + 0x28)
        if kind == KIND_MESH:
            n, r.vlist = struct.unpack_from('<HxxI', b, o + 0x34)
            for i in range(n):
                t = o + 0x3C + i * 20
                a, bb, c, attr = struct.unpack_from('<4H', b, t)
                r.tris.append((a, bb, c, attr, struct.unpack_from('<3f', b, t + 8)))
        recs.append(r)
        o += size + 0xC
    return recs, vlists


def triangles(b):
    """Flat list of (v0, v1, v2, normal, surface_type) in world space."""
    recs, vlists = collision(b)
    out = []
    for r in recs:
        if r.kind != KIND_MESH:
            continue
        vs = vlists[r.vlist].verts
        for a, bb, c, _attr, n in r.tris:
            out.append((vs[a], vs[bb], vs[c], n, r.type))
    return out


def check_collision(b):
    """Counts of problems: out-of-range indices, non-unit normals, normals against the winding."""
    recs, vlists = collision(b)
    bad_idx = bad_len = flipped = total = 0
    for r in recs:
        if r.kind != KIND_MESH:
            continue
        vs = vlists[r.vlist].verts if r.vlist < len(vlists) else []
        for a, bb, c, _attr, n in r.tris:
            total += 1
            if max(a, bb, c) >= len(vs):
                bad_idx += 1
                continue
            if abs(math.sqrt(sum(x * x for x in n)) - 1) > 0.01:
                bad_len += 1
            A, B, C = vs[a], vs[bb], vs[c]
            u = [B[i] - A[i] for i in range(3)]
            v = [C[i] - A[i] for i in range(3)]
            cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            if sum(cr[i] * n[i] for i in range(3)) < 0:
                flipped += 1
    return dict(triangles=total, bad_index=bad_idx, bad_normal=bad_len, flipped=flipped)


MD00_SLOTS = 80


def md00(b):
    """The stage models list: (names, animation names, [(alr root, animation)]) for its 80 slots.
    'NOUSE' / -1 = empty."""
    o = struct.unpack_from('<I', b, H_MD00)[0]
    if o == NONE or bytes(b[o:o + 4]) != b'MD00':
        return None
    n = struct.unpack_from('<I', b, o + 12)[0]
    p, strs = o + 16, []
    for _ in range(2 * n):
        e = bytes(b).index(b'\0', p)
        strs.append(bytes(b[p:e]).decode('ascii', 'replace'))
        p = e + 1
    pairs = [struct.unpack_from('<2i', b, p + 8 * i) for i in range(n)]
    return strs[:n], strs[n:], pairs


def set_md00(b, names, anims, pairs):
    """New .dat with this models list, appended and repointed (the old one stays, unused)."""
    buf = bytearray(b)
    buf += b'\0' * (-len(buf) % 4)
    a = b''.join(x.encode('ascii', 'replace') + b'\0' for x in names)
    c = b''.join(x.encode('ascii', 'replace') + b'\0' for x in anims)
    off = len(buf)
    buf += b'MD00' + struct.pack('<III', len(a), len(c), len(names)) + a + c
    buf += b''.join(struct.pack('<2i', *pr) for pr in pairs) + b'\0' * 8
    struct.pack_into('<I', buf, H_MD00, off)
    struct.pack_into('<I', buf, H_FILE_SIZE, len(buf))
    return bytes(buf)
