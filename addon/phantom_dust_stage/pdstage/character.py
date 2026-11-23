"""Characters: read player / enemy / NPC models (.alr), their animations (.alr runs, .ala, .ak bundles) and
textures; the writer is in char_build.py.

Layouts are from Tinkerer_Red's format reference (PHANTOM_DUST_FORMATS_REFERENCE.md, sections 3.3-3.8, 3.13),
checked against the 2017 release:

- A character .alr holds animation runs first (chunk 0x05 tracks; the run index is the motion id) and then model
  runs: 0x01 materials, 0x03 skeleton, 0x16 vertex buffers, 0x02 draws, 0x0D end, 0x00. The first model run is the
  body; further model runs are cloth and props with their own small skeletons.
- Skinned vertices (formats 0x11 and 0x05): position, UV (s16 / 32767), then at stride - 8 a colour
  (byte +2 = weight of joint a, byte +1 = weight of joint b, byte +0 mirror flag, byte +3 texture-1 alpha) and two
  s16 shader-constant slots a, b. Slot v names palette entry k = (v - 120) / 3 for v >= 120, else 24 + v / 3;
  96 = no second joint. The draw's palette (u8 skeleton joint numbers) follows its index list.
- Skeleton joints (0x40 bytes): translation, Euler rotation (radians, X then Y then Z), scale, flags, index, 0,
  parent, base-40 name, four extra floats (cloth). Local matrix (column vectors) = T * Rz * Ry * Rx * S.
- Animation track (chunk 0x05): length (frames), joint, rotation key size, key counts (translation, rotation,
  scale), rotation code, translation code, translation key size; then translation keys, rotation keys (padded to
  4), scale keys. Rotation values are angles in units of pi / 16384, order X, Y, Z; slerp between keys. An axis
  without keys in a keyed channel is 0; a channel without keys keeps the rest value. One frame per 30 Hz tick.
"""
import math
import struct

from . import alr

FPS = 30
ANGLE = math.pi / 16384.0          # rotation key unit
NO_JOINT_SLOT = 96
SKINNED_FORMATS = (0x05, 0x11)

# rotation codes: (stride, frame type, which axes the stored values are)
ROT_CODES = {0: (8, 'h', 'xyz'), 1: (6, 'h', 'xy'), 2: (6, 'h', 'xz'), 3: (6, 'h', 'yz'),
             4: (4, 'h', 'x'), 5: (4, 'h', 'y'), 6: (4, 'h', 'z'),
             7: (7, 'B', 'xyz'), 8: (5, 'B', 'xy'), 9: (5, 'B', 'xz'), 10: (5, 'B', 'yz'),
             11: (3, 'B', 'x'), 12: (3, 'B', 'y'), 13: (3, 'B', 'z')}
# translation codes: (stride, axes)
POS_CODES = {0: (16, 'xyz'), 1: (12, 'xy'), 2: (12, 'xz'), 3: (12, 'yz'), 4: (8, 'x'), 5: (8, 'y'), 6: (8, 'z')}
AXIS = {'x': 0, 'y': 1, 'z': 2}

# Character list (Phantom Dust wiki "Characters List", Torphedo): id -> (category, name)
CHARACTERS = [
    ('pc00a', 'Playable', 'Alpha'), ('evpc00a', 'Playable', 'Alpha (underground)'), ('pc01a', 'Playable', 'Edgar'),
    ('pc02a', 'Playable', 'Freia'), ('pc03a', 'Playable', 'Meister'), ('pc04a', 'Playable', 'Chunky'),
    ('pc05a', 'Playable', 'Cuff Button'), ('pc06a', 'Playable', 'pH'), ('pc07a', 'Playable', 'Know'),
    ('pc08a', 'Playable', 'Tsubutaki'), ('pc09a', 'Playable', 'JD'), ('pc10a', 'Playable', 'Sammah'),
    ('npc00a', 'NPC', 'Leader'), ('npc01a', 'NPC', '03'), ('npc02a', 'NPC', 'Spokesman'),
    ('npc03a', 'NPC', 'Ubiquitous'), ('npc04a', 'NPC', 'Kajikawa'), ('npc05a', 'NPC', 'Tetsuya'),
    ('npc06a', 'NPC', 'Arthur'), ('npc07a', 'NPC', 'Reindeer'), ('npc08a', 'NPC', 'Mac'),
    ('npc09a', 'NPC', 'Baroness'), ('npc10a', 'NPC', 'Mikan'), ('npc11a', 'NPC', 'Ai'), ('npc12a', 'NPC', 'Maniac'),
    ('npc13a', 'NPC', 'Kei'),
    ('enm00a', 'Enemy', 'Ommato'), ('enm01a', 'Enemy', 'Scoto'), ('enm02a', 'Enemy', 'Claustro'),
    ('enm03a', 'Enemy', 'Catoptro'), ('enm04a', 'Enemy', 'Mechano'), ('enm05a', 'Enemy', 'Gyne'),
    ('enm06a', 'Enemy', 'Euroto'), ('enm07a', 'Enemy', 'Hedono'), ('enm08a', 'Enemy', 'Anthro'),
    ('enm09a', 'Enemy', 'Andro'), ('enm10a', 'Enemy', 'Vestio'), ('enm11a', 'Enemy', 'Partheno'),
    ('enm12a', 'Enemy', 'Guard'), ('enm13a', 'Enemy', 'Ceno'), ('enm14a', 'Enemy', 'Germano'),
    ('enm15a', 'Enemy', 'Belono'),
    ('boss00', 'Boss', 'Peccato (Clam)'), ('boss01', 'Boss', 'Thalasso (Flyer)'), ('boss02', 'Boss', 'Carcino (Spider)'),
    ('boss03', 'Boss', 'Demented Freia (Part 1 Climb)'), ('boss03b', 'Boss', 'Demented Freia (Part 2 Wings)'),
]
NAMES = {cid: name for cid, _cat, name in CHARACTERS}
BATTLE_MOTIONS = 130            # runs 0..129 of a battle model (the base pcNNa.alr has 129)
EXMOT_BASE = 130                # exmotK.ala = motion 130 + K


# ---------------------------------------------------------------- bundles (.mk models, .ak animations)

def bundle_members(b):
    """[(name, bytes)] of a .mk / .ak bundle."""
    _hs, n = struct.unpack_from('<2I', b, 0)
    offs = struct.unpack_from('<%dI' % n, b, 8)
    names = b[8 + 4 * n:].split(b'\0')[:n]
    ends = sorted(set(offs) | {len(b)})
    out = []
    for o, nm in zip(offs, names):
        if o == 0xFFFFFFFF:
            continue
        end = next(e for e in ends if e > o)
        out.append((nm.decode('ascii', 'replace'), b[o:end]))
    return out


# ---------------------------------------------------------------- skeleton

def read_skeleton(b, off, size):
    """Joints of a 0x03 chunk: list of dicts (t, rot, scale, flags, index, parent, name, extra, raw)."""
    count = struct.unpack_from('<H', b, off + 8)[0]
    joints = []
    for i in range(count):
        e = off + 0x10 + 0x40 * i
        f = struct.unpack_from('<9f', b, e)
        flags, idx, _z, parent = struct.unpack_from('<HHHh', b, e + 0x24)
        word = struct.unpack_from('<I', b, e + 0x2C)[0]
        joints.append(dict(t=f[0:3], rot=f[3:6], scale=f[6:9], flags=flags, index=idx,
                           parent=None if parent < 0 else parent,
                           name='' if word == 0xFFFFFFFF else alr.decode_text(word),
                           extra=struct.unpack_from('<4f', b, e + 0x30), raw=bytes(b[e:e + 0x40])))
    return joints


def euler_matrix(rx, ry, rz):
    """3x3 rotation (column vectors) Rz * Ry * Rx."""
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def local_matrix(t, rot, scale=(1, 1, 1)):
    r = euler_matrix(*rot)
    return [[r[i][0] * scale[0], r[i][1] * scale[1], r[i][2] * scale[2], t[i]] for i in range(3)] + [[0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def world_matrices(joints, locals_=None):
    """Model-space matrices of every joint (parents always come before children in the game's files, but
    this does not rely on it)."""
    loc = locals_ or [local_matrix(j['t'], j['rot'], j['scale']) for j in joints]
    out = [None] * len(joints)

    def get(i, depth=0):
        if out[i] is None:
            p = joints[i]['parent']
            out[i] = loc[i] if p is None or depth > 512 else mul(get(p, depth + 1), loc[i])
        return out[i]
    for i in range(len(joints)):
        get(i)
    return out


def apply(m, v):
    return tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3))


# ---------------------------------------------------------------- textures

def _expand(v, bits):
    return (v << (8 - bits)) | (v >> (2 * bits - 8)) if bits < 8 else v


def decode_texture(b, t):
    """Top mip of a texture as (width, height, RGBA bytes, top row first), or None (cube maps, unknown)."""
    import numpy as np
    if t['cubemap']:
        return None
    w, h = t['width'], t['height']
    start = alr.header(b)['resource_offset'] + t['offset']
    code = t['raw_format'] & 0x7F if t['raw_format'] & 0x80 else t['raw_format']
    if code in (0x0C, 0x0E, 0x0F):
        bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
        bsize = 8 if code == 0x0C else 16
        data = np.frombuffer(b, dtype=np.uint8, count=bw * bh * bsize, offset=start).reshape(bw * bh, bsize)
        rgba = _decode_dxt(np, data, code)
        img = rgba.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)[:h, :w]
        return w, h, img.astype(np.uint8).tobytes()
    if code in (0x02, 0x04, 0x05):
        px = np.frombuffer(b, dtype='<u2', count=w * h, offset=start).astype(np.uint32)
        if code == 0x02:      # A1R5G5B5
            r, g, bl, a = (px >> 10) & 31, (px >> 5) & 31, px & 31, (px >> 15) * 255
            r, g, bl = (c << 3 | c >> 2 for c in (r, g, bl))
        elif code == 0x04:    # A4R4G4B4
            a, r, g, bl = (((px >> s) & 15) * 17 for s in (12, 8, 4, 0))
        else:                 # R5G6B5
            r, g, bl = (px >> 11) & 31, (px >> 5) & 63, px & 31
            r, g, bl = r << 3 | r >> 2, g << 2 | g >> 4, bl << 3 | bl >> 2
            a = np.full_like(px, 255)
        img = np.stack([r, g, bl, a], -1).astype(np.uint8)
        return w, h, img.tobytes()
    if code in (0x06, 0x12):
        px = np.frombuffer(b, dtype=np.uint8, count=w * h * 4, offset=start).reshape(-1, 4)
        return w, h, px[:, [2, 1, 0, 3]].copy().tobytes()
    if code in (0x00, 0x13, 0x1F):
        px = np.frombuffer(b, dtype=np.uint8, count=w * h, offset=start)
        if code == 0x1F:
            img = np.stack([np.full_like(px, 255)] * 3 + [px], -1)
        else:
            img = np.stack([px, px, px, np.full_like(px, 255)], -1)
        return w, h, img.astype(np.uint8).tobytes()
    return None


def _decode_dxt(np, data, code):
    """(n, 8 or 16) block bytes -> (n, 16, 4) RGBA, texels in row order inside each block."""
    col = data[:, -8:]
    c0 = col[:, 0].astype(np.uint32) | (col[:, 1].astype(np.uint32) << 8)
    c1 = col[:, 2].astype(np.uint32) | (col[:, 3].astype(np.uint32) << 8)

    def rgb(c):
        r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
        return np.stack([r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2], -1).astype(np.float32)
    a0, a1 = rgb(c0), rgb(c1)
    four = (c0 > c1) | (code != 0x0C)
    p2 = np.where(four[:, None], (2 * a0 + a1) / 3, (a0 + a1) / 2)
    p3 = np.where(four[:, None], (a0 + 2 * a1) / 3, 0)
    pal = np.stack([a0, a1, p2, p3], 1)                                       # (n, 4, 3)
    bits = col[:, 4:8].astype(np.uint32)
    idx = (bits[:, 0] | bits[:, 1] << 8 | bits[:, 2] << 16 | bits[:, 3] << 24)[:, None] >> (2 * np.arange(16)) & 3
    out = np.empty((len(data), 16, 4), np.float32)
    out[:, :, :3] = np.take_along_axis(pal, idx[:, :, None].repeat(3, 2), 1)
    if code == 0x0C:
        out[:, :, 3] = np.where((~four[:, None]) & (idx == 3), 0, 255)
    elif code == 0x0E:
        al = data[:, :8].astype(np.uint32)
        nib = np.stack([(al[:, i // 2] >> (4 * (i % 2))) & 15 for i in range(16)], 1)
        out[:, :, 3] = nib * 17
    else:
        e0, e1 = data[:, 0].astype(np.float32), data[:, 1].astype(np.float32)
        ab = data[:, 2:8].astype(np.uint64)
        word = sum(ab[:, i] << np.uint64(8 * i) for i in range(6))
        ai = (word[:, None] >> (np.uint64(3) * np.arange(16, dtype=np.uint64))) & np.uint64(7)
        ai = ai.astype(np.int64)
        e8 = e0 > e1
        vals = np.empty((len(data), 8), np.float32)
        vals[:, 0], vals[:, 1] = e0, e1
        for k in range(1, 7):
            vals[:, k + 1] = np.where(e8, ((7 - k) * e0 + k * e1) / 7, ((5 - k) * e0 + k * e1) / 5 if k < 5 else 0)
        vals[:, 6] = np.where(e8, vals[:, 6], 0)
        vals[:, 7] = np.where(e8, vals[:, 7], 255)
        out[:, :, 3] = np.take_along_axis(vals, ai, 1)
    return np.clip(np.round(out), 0, 255)


# ---------------------------------------------------------------- models

def _palette(b, off, nidx):
    p = off + 0x68 + 2 * nidx + (2 if nidx % 2 else 0)
    if p + 8 > len(b):
        return []
    _z, n = struct.unpack_from('<2I', b, p)
    if n == 0 or n > 64:
        return []
    return list(b[p + 8:p + 8 + n])


def slot_to_palette(v):
    return (v - 120) // 3 if v >= 120 else 24 + v // 3


def read_model(b, root):
    """One model run: dict(materials, joints, vbufs, draws). Each draw: material, joint, vbuf, primitive,
    first, count, indices, palette, raw header (0x68 bytes)."""
    mats, joints, vbufs, draws, extra = [], [], [], [], []
    mat_header = b'\0\0\0\0'
    for off, t, size in alr.chain(b, root):
        if t == 0x01:
            mats = alr._materials(b, off)
            mat_header = bytes(b[off + 8:off + 12])
            for m in mats:
                m['flags'] = struct.unpack_from('<I', m['raw'], 0x0C)[0]
                m['roles'] = struct.unpack_from('<H', m['raw'], 0x16)[0]
        elif t == 0x03:
            joints = read_skeleton(b, off, size)
        elif t == 0x16:
            vbufs = alr._vertex_buffers(b, off)
            for i, vb in enumerate(vbufs):
                vb['raw'] = bytes(b[off + 0xC + 0x1C * i:off + 0xC + 0x1C * (i + 1)])
        elif t == 0x02:
            mat, joint, vb, prim = struct.unpack_from('<4H', b, off + 0x40)
            first, count, nidx = struct.unpack_from('<3I', b, off + 0x48)
            idx = list(struct.unpack_from('<%dH' % nidx, b, off + 0x68))
            draws.append(dict(material=mat, joint=joint, vbuf=vb, primitive=prim, first=first, count=count,
                              indices=idx, palette=_palette(b, off, nidx), raw=bytes(b[off:off + 0x68]),
                              size=size))
        elif t not in (0x00, 0x0D):
            extra.append((t, bytes(b[off:off + size])))
    return dict(materials=mats, joints=joints, vbufs=vbufs, draws=draws, extra=extra, mat_header=mat_header)


def draw_vertices(b, model, draw):
    """Vertices a draw uses: (positions in model space, uvs, weights [(joint, w), ...], index triples into these
    lists, vertex numbers in the buffer). Positions get the draw joint's bind matrix applied (identity for most
    skinned draws); rigid draws are bound fully to their joint."""
    vb = model['vbufs'][draw['vbuf']]
    fmt, stride = vb['format'], vb['vertex_size']
    rb = alr.header(b)['resource_offset'] + vb['offset']
    idx = draw['indices']
    tris = alr.triangles_from_indices(idx, draw['primitive'])
    base = 0          # indices are absolute vertex numbers (the start vertex is their minimum)
    used = sorted({i for t in tris for i in t})
    remap = {v: k for k, v in enumerate(used)}
    bind = world_matrices(model['joints'])
    jm = bind[draw['joint']] if draw['joint'] < len(bind) else None
    uv_at = {0x11: 0x0C, 0x05: 0x10, 0x01: 0x10, 0x03: 0x10, 0x09: 0x0C, 0x15: 0x0C}.get(fmt)
    pos, uvs, weights = [], [], []
    pal = draw['palette']
    for v in used:
        o = rb + (base + v) * stride
        p = struct.unpack_from('<3f', b, o)
        pos.append(apply(jm, p) if jm else p)
        if uv_at is not None:
            u, w = struct.unpack_from('<2h', b, o + uv_at)
            div = 32767.0 if fmt in SKINNED_FORMATS else 4096.0
            uvs.append((u / div, w / div))
        else:
            uvs.append((0.0, 0.0))
        if fmt in SKINNED_FORMATS and pal:
            c = b[o + stride - 8:o + stride - 4]
            sa, sb = struct.unpack_from('<2h', b, o + stride - 4)
            ws = []
            ka = slot_to_palette(sa)
            if c[2] and 0 <= ka < len(pal):
                ws.append((pal[ka], c[2] / 255.0))
            if sb != NO_JOINT_SLOT and c[1]:
                kb = slot_to_palette(sb)
                if 0 <= kb < len(pal):
                    ws.append((pal[kb], c[1] / 255.0))
            weights.append(ws or [(draw['joint'], 1.0)])
        else:
            weights.append([(draw['joint'], 1.0)])
    return pos, uvs, weights, [tuple(remap[i] for i in t) for t in tris], [base + v for v in used]


def vertex_extras(b, model, draw, numbers):
    """Per vertex: (mirror byte, texture-1 alpha byte) of skinned vertices, kept for export."""
    vb = model['vbufs'][draw['vbuf']]
    if vb['format'] not in SKINNED_FORMATS:
        return [(0, 255)] * len(numbers)
    rb = alr.header(b)['resource_offset'] + vb['offset']
    out = []
    for n in numbers:
        c = b[rb + n * vb['vertex_size'] + vb['vertex_size'] - 8:][:4]
        out.append((c[0], c[3]))
    return out


# shader classes that are not the visible body: shadow volumes and the aura hull
HIDDEN_SHADERS = ('sshadowch', 'saura')


def model_roots(b):
    """Root indices of the model runs (those with draw chunks), in file order."""
    h = alr.header(b)
    return [i for i, r in enumerate(h['roots']) if r < len(b) and any(t == 0x02 for _, t, _ in alr.chain(b, r))]


def animation_roots(b):
    h = alr.header(b)
    return [i for i, r in enumerate(h['roots']) if r < len(b) and any(t == 0x05 for _, t, _ in alr.chain(b, r))]


# ---------------------------------------------------------------- animation

def read_tracks(b, off):
    """Tracks of a chunk-0x05 run starting at `off`: list of dicts (joint, length, T, R, S) with keys
    T: [(frame, {axis: value})], R: [(frame, {axis: angle radians})], S: [(frame, (sx, sy, sz))]."""
    out = []
    j = off
    while j + 8 <= len(b):
        cid, size = struct.unpack_from('<Ii', b, j)
        if cid != 5 or size < 0x20:
            break
        length, joint, rks = struct.unpack_from('<fHB', b, j + 8)
        nt, nr, ns = struct.unpack_from('<3I', b, j + 0x10)
        rc, tc, tks = struct.unpack_from('<3B', b, j + 0x1C)
        tks = tks or 16
        p = j + 0x20
        T, R, S = [], [], []
        tstride, taxes = POS_CODES.get(tc, (16, 'xyz'))
        for k in range(nt):
            vals = struct.unpack_from('<%df' % (1 + len(taxes)), b, p + k * tks)
            T.append((vals[0], {a: v for a, v in zip(taxes, vals[1:])}))
        p += nt * tks
        rstride, ftype, raxes = ROT_CODES.get(rc if rc <= 13 else 0)
        for k in range(nr):
            q = p + k * rks
            if ftype == 'h':
                frame = struct.unpack_from('<h', b, q)[0]
                vals = struct.unpack_from('<%dH' % len(raxes), b, q + 2)
            else:
                frame = b[q]
                vals = struct.unpack_from('<%dH' % len(raxes), b, q + 1)
            R.append((frame, {a: _angle(v) for a, v in zip(raxes, vals)}))
        p += nr * rks
        p += (-(p - j)) % 4
        for k in range(ns):
            S.append((lambda f: (f[0], f[1:4]))(struct.unpack_from('<4f', b, p + 16 * k)))
        out.append(dict(joint=joint, length=length, T=T, R=R, S=S, rot_code=rc, pos_code=tc))
        j += size
    return out


def _angle(v):
    """u16 angle -> radians (-pi..pi)."""
    if v >= 32768:
        v -= 65536
    return v * ANGLE


def run_tracks(b, run):
    h = alr.header(b)
    r = h['roots'][run]
    return read_tracks(b, r) if r < len(b) else []


def clip_length(tracks):
    return max([t['length'] for t in tracks] + [0.0])


def _q_from_euler(rx, ry, rz):
    """Quaternion (w, x, y, z) of Rz * Ry * Rx."""
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    return (cz * cy * cx + sz * sy * sx, cz * cy * sx - sz * sy * cx, cz * sy * cx + sz * cy * sx,
            sz * cy * cx - cz * sy * sx)


def _slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-x for x in b), -d
    if d > 0.9995:
        r = tuple(x + (y - x) * t for x, y in zip(a, b))
    else:
        th = math.acos(d)
        s = math.sin(th)
        wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        r = tuple(wa * x + wb * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in r)) or 1.0
    return tuple(x / n for x in r)


def _bracket(keys, f):
    """Index pair and blend for frame f (clamped at the ends)."""
    if f <= keys[0][0]:
        return 0, 0, 0.0
    for k in range(len(keys) - 1):
        f0, f1 = keys[k][0], keys[k + 1][0]
        if f0 <= f < f1:
            return k, k + 1, (f - f0) / (f1 - f0) if f1 > f0 else 0.0
    return len(keys) - 1, len(keys) - 1, 0.0


def sample(track, joint, f):
    """Local (translation, quaternion (w, x, y, z), scale) of a joint at frame f."""
    if track and track['T']:
        a, b_, t = _bracket(track['T'], f)
        ka, kb = track['T'][a][1], track['T'][b_][1]
        pos = tuple(ka.get(ax, 0.0) + (kb.get(ax, 0.0) - ka.get(ax, 0.0)) * t for ax in 'xyz')
    else:
        pos = tuple(joint['t'])
    if track and track['R']:
        a, b_, t = _bracket(track['R'], f)
        qa = _q_from_euler(*(track['R'][a][1].get(ax, 0.0) for ax in 'xyz'))
        qb = _q_from_euler(*(track['R'][b_][1].get(ax, 0.0) for ax in 'xyz'))
        rot = _slerp(qa, qb, t)
    else:
        rot = _q_from_euler(*joint['rot'])
    if track and track['S']:
        a, b_, t = _bracket(track['S'], f)
        sa, sb = track['S'][a][1], track['S'][b_][1]
        scale = tuple(x + (y - x) * t for x, y in zip(sa, sb))
    else:
        scale = tuple(joint['scale'])
    return pos, rot, scale


def quat_matrix(q, t=(0, 0, 0), s=(1, 1, 1)):
    w, x, y, z = q
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)] + [[0, 0, 0, 1]]


def pose(joints, tracks, f):
    """Model-space matrices of every joint at frame f."""
    by_joint = {t['joint']: t for t in tracks}
    loc = []
    for i, j in enumerate(joints):
        p, q, s = sample(by_joint.get(i), j, f)
        loc.append(quat_matrix(q, p, s))
    return world_matrices(joints, loc)


# ---------------------------------------------------------------- whole file as plain data (tests, exporter)

def texture_bytes(b, t):
    """Every mip level of a texture as stored."""
    w, h, mips = t['width'], t['height'], max(1, t['mips'])
    code = t['raw_format'] & 0x7F if t['raw_format'] & 0x80 else t['raw_format']
    per = {0x0C: 8, 0x0E: 16, 0x0F: 16}.get(code)
    bpp = {0x00: 1, 0x13: 1, 0x1F: 1, 0x02: 2, 0x04: 2, 0x05: 2, 0x06: 4, 0x12: 4, 0x28: 2}.get(code, 4)
    size = 0
    for k in range(mips):
        ww, hh = max(1, w >> k), max(1, h >> k)
        size += max(1, (ww + 3) // 4) * max(1, (hh + 3) // 4) * per if per else ww * hh * bpp
    start = alr.header(b)['resource_offset'] + t['offset']
    return bytes(b[start:start + size])


def read_ir(b):
    """(textures, models, anims) of a character file in char_build's input format; animation runs are kept as
    their raw bytes."""
    h = alr.header(b)
    textures = [dict(name=t['name'], raw_format=t['raw_format'], width=t['width'], height=t['height'],
                     mips=max(1, t['mips']), data=texture_bytes(b, t)) for t in alr.textures(b)]
    anims = {}
    for i in animation_roots(b):
        r = h['roots'][i]
        c = alr.chain(b, r)
        anims[i] = bytes(b[r:c[-1][0] + c[-1][2]])
    models = []
    for i in model_roots(b):
        r = h['roots'][i]
        m = read_model(b, r)
        hdr = None
        for off, t, size in alr.chain(b, r):
            if t == 0x01:
                hdr = bytes(b[off + 8:off + 12])
        skin, rigid = [], []
        draw_joint = 0
        for d in m['draws']:
            mat = m['materials'][d['material']]
            vb = m['vbufs'][d['vbuf']]
            pos, uvs, ws, tris, nums = draw_vertices(b, m, d)
            if vb['format'] in SKINNED_FORMATS:
                draw_joint = d['joint']
                ex = vertex_extras(b, m, d, nums)
                skin.append(dict(material=d['material'], verts=[(p, u, w, e[0], e[1]) for p, u, w, e in
                                                                 zip(pos, uvs, ws, ex)], tris=tris))
            else:
                rb = h['resource_offset'] + vb['offset']
                extra = []
                for n in nums:
                    o = rb + n * vb['vertex_size'] + 12
                    if vb['format'] == 0x07:
                        v = struct.unpack_from('<I', b, o)[0]
                        nx = ((v & 0x7FF) ^ 0x400) - 0x400
                        ny = (((v >> 11) & 0x7FF) ^ 0x400) - 0x400
                        nz = (((v >> 22) & 0x3FF) ^ 0x200) - 0x200
                        jm = world_matrices(m['joints'])[d['joint']]
                        nl = (nx / 1023.0, ny / 1023.0, nz / 511.0)
                        extra.append(tuple(jm[r_][0] * nl[0] + jm[r_][1] * nl[1] + jm[r_][2] * nl[2] for r_ in range(3)))
                    else:
                        extra.append(tuple(b[o:o + 4]))
                rigid.append(dict(material=d['material'], format=vb['format'], joint=d['joint'],
                                  verts=list(zip(pos, extra)), tris=tris))
        masks = {vb['format']: struct.unpack_from('<I', vb['raw'], 4)[0] for vb in m['vbufs']}
        models.append(dict(joints=m['joints'], materials=[x['raw'] for x in m['materials']], mat_header=hdr,
                           vbuf_masks=masks, skin=skin, rigid=rigid, draw_joint=draw_joint,
                           extra=[raw for _t, raw in m['extra']]))
    return textures, models, anims


# ---------------------------------------------------------------- joint matching and retargeting

def joint_keys(joints):
    """A key per joint that is the same for the matching joint of another character's skeleton: the name for
    named joints; for unnamed ones the nearest named ancestor and the path of unnamed-child ranks to it; for
    unnamed joints above every named one (the root chain), the first named descendant and the distance to it.
    Joints with neither (draw nodes) get None."""
    kids = {}
    for i, j in enumerate(joints):
        kids.setdefault(j['parent'], []).append(i)
    out = {}
    for i, j in enumerate(joints):
        if j['name']:
            out[i] = j['name']
            continue
        path, c = [], i
        while c is not None and not joints[c]['name']:
            p = joints[c]['parent']
            sib = [k for k in kids.get(p, []) if not joints[k]['name']]
            path.append(sib.index(c))
            c = p
        if c is not None:
            out[i] = (joints[c]['name'], tuple(reversed(path)))
            continue
        q, found = [(i, 0)], None
        while q:
            c, d = q.pop(0)
            if joints[c]['name']:
                found = ('^' + joints[c]['name'], d)
                break
            q += [(x, d + 1) for x in kids.get(c, [])]
        out[i] = found
    return out


def match_joints(src, dst):
    """{dst joint: src joint} for joints with the same key (see joint_keys)."""
    ks = {k: i for i, k in joint_keys(src).items() if k is not None}
    return {i: ks[k] for i, k in joint_keys(dst).items() if k is not None and k in ks}


def bake_clip(src_joints, tracks, dst_joints=None, mapping=None, step=1.0):
    """Keys per joint: {joint: [(frame, t or None, q, s or None)]} sampled every `step` frames, for the joints
    the tracks animate. With dst_joints and mapping ({dst: src}) the clip is moved onto another skeleton:
    rotations are copied (the game's keys are absolute local rotations), translations keep the destination's
    rest offset plus the source's movement scaled by the ratio of the two rest offsets."""
    length = clip_length(tracks)
    frames = [k * step for k in range(int(length / step) + 1)]
    if frames and frames[-1] < length:
        frames.append(length)
    by_joint = {t['joint']: t for t in tracks}
    if dst_joints is None:
        dst_joints, mapping = src_joints, {i: i for i in range(len(src_joints))}
    out = {}
    for d, s in mapping.items():
        tr = by_joint.get(s)
        if tr is None or d >= len(dst_joints):
            continue
        sj, dj = src_joints[s], dst_joints[d]
        rs = math.sqrt(sum(x * x for x in sj['t']))
        rd = math.sqrt(sum(x * x for x in dj['t']))
        ratio = rd / rs if rs > 1e-4 else 1.0
        keys = []
        for f in frames:
            p, q, sc = sample(tr, sj, f)
            t = None
            if tr['T']:
                t = tuple(dj['t'][k] + (p[k] - sj['t'][k]) * ratio for k in range(3)) if dst_joints is not src_joints \
                    else p
            keys.append((f, t, q if tr['R'] else None, sc if tr['S'] else None))
        out[d] = keys
    return out, length


def clip_tracks(keys, length):
    """bake_clip output -> char_build track dicts."""
    return [dict(joint=j, length=length, keys=k) for j, k in sorted(keys.items())]
