"""Write a character .alr (battle model: animation runs, then model runs) from parts.

Input (plain Python data, built by the Blender exporter or by character.read_ir for tests):

    textures: [dict(name, raw_format, width, height, mips, data)]           already encoded, every mip level
              or dict(name, rgba=(w, h, bytes), kind='color' | 'normal')     encoded here
    models:   [dict(joints, materials, mat_header, vbuf_masks, skin, rigid, draw_joint, extra)]
        joints     [dict(t, rot, scale, flags, name, parent, extra)]          game space, radians
        materials  [bytes (0x4C)]: the record; texture indices (+0x18) are file-wide indices
        mat_header bytes (4): count is rewritten, the second u16 kept
        vbuf_masks {format: attribute mask}
        skin       [dict(material, verts=[(pos, uv, [(joint, w)], mirror, alpha)], tris=[(a, b, c)])]
                   pos in model space; split into draws of at most PALETTE joints and 65,535 vertices
        rigid      [dict(material, format, joint, verts=[(pos_model_space, normal_or_colour)], tris)]
                   format 0x07 (shadow volume: normal) or 0x0B (aura hull: BGRA colour bytes)
        draw_joint joint number of an identity joint skinned draws are attached to
        extra      [bytes]: other chunks of the model run kept as they were (0x13 effect parameters)
    anims:    {run index: [track dict(joint, length, keys=[(frame, t or None, q (w, x, y, z), s or None)])]}
              or {run index: bytes} (a chain copied as it is, terminator included)
    header:   the first 0x20 bytes of a game character file (copied; offsets and sizes are rewritten)

Layout details measured on the game's files (pc00a0, pc01a0, pc02a0, enm09a0):
- skeleton chunk: 16-byte header, 64-byte joints, then one identity matrix per joint and 160 more bytes of the
  same pattern (runtime space);
- skinned draw: 0x68 header, u16 indices, 2 bytes of padding when the count is odd, u32 0, u32 n, u8 joints[n],
  padding to 4, n identity matrices, then 32 more bytes (runtime space);
- rigid draw: header and indices (padded to 4);
- vertex data and textures live in the resource buffer after the chunk area (which is padded to 0x1000).
"""
import math
import struct

from . import alr, character
from .alr_build import encode_text, pack_normal

PALETTE = 24            # joints per skinned draw (the slots without the wrap; the game allows up to 34)
MAX_VERTS = 0xFFFF
ALIGN = 0x100
IDENTITY = struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
SKEL_TAIL = (IDENTITY * 3)[:160]
DRAW_TAIL = IDENTITY[:32]
SKIN_FORMAT, SKIN_STRIDE = 0x11, 24
RIGID_STRIDE = {0x07: 16, 0x0B: 16}
DEFAULT_MASKS = {0x11: 0x647, 0x07: 0x0F, 0x0B: 0x87}
END = struct.pack('<II', 0, 8)


# ---------------------------------------------------------------- animation

def euler_from_quat(q):
    """(rx, ry, rz) with R = Rz * Ry * Rx (the game's order)."""
    w, x, y, z = q
    m20 = 2 * (x * z - y * w)
    m21 = 2 * (y * z + x * w)
    m22 = 1 - 2 * (x * x + y * y)
    m10 = 2 * (x * y + z * w)
    m00 = 1 - 2 * (y * y + z * z)
    ry = math.asin(max(-1.0, min(1.0, -m20)))
    if abs(m20) < 0.99999:
        rx = math.atan2(m21, m22)
        rz = math.atan2(m10, m00)
    else:                                   # gimbal lock: rz = 0, R = Ry * Rx
        m12 = 2 * (y * z - x * w)
        m11 = 1 - 2 * (x * x + z * z)
        rx = math.atan2(-m12, m11)
        rz = 0.0
    return rx, ry, rz


def _u16(angle):
    return int(round(angle / character.ANGLE)) & 0xFFFF


ROT_TOLERANCE = 0.0015        # radians; keys closer than this to the interpolation of their neighbours are dropped
POS_TOLERANCE = 0.002         # game units


def _reduce(keys, error):
    """Drop keys that the interpolation between the kept neighbours reproduces (first and last always kept)."""
    if len(keys) <= 2:
        return keys
    out = [keys[0]]
    for k in range(1, len(keys) - 1):
        a, b, c = out[-1], keys[k], keys[k + 1]
        t = (b[0] - a[0]) / (c[0] - a[0]) if c[0] > a[0] else 0.0
        if error(a[1], b[1], c[1], t):
            out.append(b)
    out.append(keys[-1])
    return out


def _pos_error(a, b, c, t):
    return any(abs(a[i] + (c[i] - a[i]) * t - b[i]) > POS_TOLERANCE for i in range(3))


def _rot_error(a, b, c, t):
    m = character._slerp(a, c, t)
    d = abs(sum(x * y for x, y in zip(m, b)))
    return 2 * math.acos(min(1.0, d)) > ROT_TOLERANCE


def encode_track(track, reduce=True):
    """Chunk-0x05 bytes of one track. keys: [(frame, t or None, q, s or None)] (t, s None = not keyed)."""
    keys = sorted(track['keys'], key=lambda k: k[0])
    tk = [(f, t) for f, t, _q, _s in keys if t is not None]
    rk = [(f, q) for f, _t, q, _s in keys if q is not None]
    sk = [(f, s) for f, _t, _q, s in keys if s is not None]
    if reduce:
        tk, rk, sk = _reduce(tk, _pos_error), _reduce(rk, _rot_error), _reduce(sk, _pos_error)
    last = max([k[0] for k in keys] + [0])
    short = last <= 255 and all(float(f).is_integer() for f, _ in rk)
    rc, rks = (7, 7) if short else (0, 8)
    body = bytearray()
    for f, t in tk:
        body += struct.pack('<4f', f, *t)
    for f, q in rk:
        rx, ry, rz = euler_from_quat(q)
        if short:
            body += struct.pack('<B3H', int(f), _u16(rx), _u16(ry), _u16(rz))
        else:
            body += struct.pack('<h3H', int(round(f)), _u16(rx), _u16(ry), _u16(rz))
    body += b'\0' * (-(24 + len(body)) % 4)
    for f, s in sk:
        body += struct.pack('<4f', f, *s)
    length = float(track.get('length', last))
    head = struct.pack('<fHBBIIIBBBB', length, track['joint'], rks, 0, len(tk), len(rk), len(sk), rc, 0, 16, 0)
    return struct.pack('<Ii', 5, 8 + len(head) + len(body)) + head + bytes(body)


def encode_run(tracks):
    """A whole animation run (tracks sorted by joint, the game's sampler needs that) plus the terminator."""
    return b''.join(encode_track(t) for t in sorted(tracks, key=lambda t: t['joint'])) + END


# ---------------------------------------------------------------- textures

def _mips(w, h, rgba, np):
    img = np.frombuffer(rgba, np.uint8).reshape(h, w, 4).astype(np.float32)
    levels = [img]
    while img.shape[0] > 1 or img.shape[1] > 1:
        hh, ww = max(1, img.shape[0] // 2), max(1, img.shape[1] // 2)
        img = img[:hh * 2 if img.shape[0] > 1 else 1, :ww * 2 if img.shape[1] > 1 else 1]
        img = img.reshape(hh, img.shape[0] // hh, ww, img.shape[1] // ww, 4).mean((1, 3))
        levels.append(img)
    return [np.clip(np.round(l), 0, 255).astype(np.uint8) for l in levels]


def encode_texture(tex):
    """dict(name, rgba=(w, h, bytes), kind) -> encoded texture dict (all mip levels)."""
    import numpy as np
    from . import dxt
    w, h, rgba = tex['rgba']
    if w & (w - 1) or h & (h - 1):
        raise ValueError('texture %s: %d x %d is not a power of two' % (tex['name'], w, h))
    levels = _mips(w, h, rgba, np)
    a0 = levels[0][..., 3]
    graded = bool(((a0 > 8) & (a0 < 247)).any())
    if tex.get('kind') == 'normal' and not graded:
        out = []
        for l in levels:                                 # A1R5G5B5, row-major (PC marker 0x80); the alpha bit is
            r, g, b = (l[..., c].astype(np.uint16) >> 3 for c in range(3))     # the shine mask (on / off)
            a = (l[..., 3] >= 128).astype(np.uint16) << 15
            out.append((a | (r << 10) | (g << 5) | b).astype('<u2').tobytes())
        fmt = 0x82
    elif tex.get('kind') == 'normal':                     # a graded shine mask: block-compressed with alpha (the
        out = []                                          # game's own use DXT3; DXT5 is the same layout family)
        fmt = None
        for l in levels:
            if l.shape[0] < 4 or l.shape[1] < 4:
                l = np.pad(l, ((0, max(0, 4 - l.shape[0])), (0, max(0, 4 - l.shape[1])), (0, 0)), mode='edge')
            fmt, data = dxt.encode(l, True)
            out.append(data)
    else:
        alpha = dxt.needs_alpha(levels[0])
        fmt = None
        out = []
        for l in levels:
            if l.shape[0] < 4 or l.shape[1] < 4:          # DXT mips below 4 x 4 take one block
                l = np.pad(l, ((0, max(0, 4 - l.shape[0])), (0, max(0, 4 - l.shape[1])), (0, 0)), mode='edge')
            f, data = dxt.encode(l, alpha)
            fmt = f
            out.append(data)
    return dict(name=tex['name'], raw_format=fmt, width=w, height=h, mips=len(out), data=b''.join(out))


def _texture_entry(t, rel):
    wp, hp = t['width'].bit_length() - 1, t['height'].bit_length() - 1
    return struct.pack('<3I4BI2I', 0x00040001, rel, 0, 0x29, t['raw_format'], (wp << 4) | (t['mips'] & 0xF),
                       hp & 0xF, 0, *encode_text(t['name'][:12]))


# ---------------------------------------------------------------- model

def _joint_record(j, i):
    raw = bytearray(j['raw']) if j.get('raw') else bytearray(0x40)
    struct.pack_into('<9f', raw, 0, *j['t'], *j['rot'], *j['scale'])
    parent = -1 if j['parent'] is None else j['parent']
    struct.pack_into('<HHHh', raw, 0x24, j.get('flags', 0) & 0xFFFF, i, 0, parent)
    name = j.get('name') or ''
    word = encode_text(name)[0] if name else 0xFFFFFFFF
    struct.pack_into('<I', raw, 0x2C, word)
    struct.pack_into('<4f', raw, 0x30, *(j.get('extra') or (0, 0, 0, 0)))
    return bytes(raw)


def skeleton_chunk(joints):
    body = struct.pack('<HHI', len(joints), 1, 0) + b''.join(_joint_record(j, i) for i, j in enumerate(joints))
    body += IDENTITY * len(joints) + SKEL_TAIL
    return struct.pack('<II', 3, 8 + len(body)) + body


def _sphere_box(points):
    if not points:
        return (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    lo = tuple(min(p[k] for p in points) for k in range(3))
    hi = tuple(max(p[k] for p in points) for k in range(3))
    c = tuple((a + b) / 2 for a, b in zip(lo, hi))
    r = max(math.sqrt(sum((p[k] - c[k]) ** 2 for k in range(3))) for p in points)
    return c, r, lo, hi


def _draw_chunk(material, joint, vbuf, first, count, indices, palette, bounds_pts):
    c, r, lo, hi = _sphere_box(bounds_pts)
    head = bytearray(0x68)
    struct.pack_into('<4f3f3f', head, 0x08, *c, r, *lo, *hi)
    struct.pack_into('<4H3I', head, 0x40, material, joint, vbuf, 5, first, count, len(indices))
    body = bytes(head[8:]) + struct.pack('<%dH' % len(indices), *indices)
    if len(indices) % 2:
        body += b'\0\0'
    if palette is not None:
        body += struct.pack('<2I', 0, len(palette)) + bytes(palette)
        body += b'\0' * (-(8 + len(body)) % 4)
        body += IDENTITY * len(palette) + DRAW_TAIL
    return struct.pack('<II', 2, 8 + len(body)) + body


def _slot(k):
    return 120 + 3 * k if k < 24 else 3 * (k - 24)


def _split_skin(verts, tris, limit=PALETTE):
    """Groups of triangles whose vertices use at most `limit` joints (and MAX_VERTS vertices):
    [(vertex numbers, local triangles, palette)]."""
    joints_of = [frozenset(j for j, w in v[2] if w > 0) for v in verts]
    order = sorted(range(len(tris)), key=lambda t: min(min(joints_of[i]) if joints_of[i] else 0 for i in tris[t]))
    groups, cur, pal, used = [], [], [], {}

    def flush():
        if cur:
            groups.append((sorted(used, key=used.get), [tuple(used[i] for i in t) for t in cur], list(pal)))
    for ti in order:
        t = tris[ti]
        need = set().union(*(joints_of[i] for i in t)) - set(pal)
        new_v = [i for i in t if i not in used]
        if len(pal) + len(need) > limit or len(used) + len(new_v) > MAX_VERTS:
            flush()
            cur, pal, used = [], [], {}
            need = set().union(*(joints_of[i] for i in t))
            if len(need) > limit:
                raise ValueError('a triangle uses %d joints (at most %d)' % (len(need), limit))
        pal += sorted(need)
        for i in t:
            used.setdefault(i, len(used))
        cur.append(t)
    flush()
    return groups


def _skin_vertex(pos, uv, weights, mirror, alpha, palette):
    ws = sorted(((j, w) for j, w in weights if w > 0), key=lambda x: -x[1])[:2]
    if not ws:
        ws = [(palette[0], 1.0)]
    total = sum(w for _, w in ws)
    ka = palette.index(ws[0][0])
    if len(ws) == 1:
        wa, wb, sb = 255, 0, 96
    else:
        wa = int(round(255 * ws[0][1] / total))
        wb = 255 - wa
        sb = _slot(palette.index(ws[1][0])) if wb else 96
    u = max(-32768, min(32767, int(round(uv[0] * 32767))))
    v = max(-32768, min(32767, int(round(uv[1] * 32767))))
    return struct.pack('<3f2h4B2h', *pos, u, v, mirror & 255, wb, wa, alpha & 255, _slot(ka), sb)


def model_chunks(model, tex_base=0):
    """(chain bytes, vertex data bytes) of one model run; vertex buffer offsets are relative to the start of
    the returned vertex data (the caller adds the position in the resource buffer: see _rebase)."""
    chunks = []
    mats = model['materials']
    hdr = bytearray(model.get('mat_header') or struct.pack('<HH', 0, 0))
    struct.pack_into('<H', hdr, 0, len(mats))
    chunks.append(struct.pack('<II', 1, 12 + 0x4C * len(mats)) + bytes(hdr) + b''.join(mats))
    chunks.append(skeleton_chunk(model['joints']))
    bind = character.world_matrices(model['joints'])
    inv = [_rigid_inverse(m) for m in bind]

    vbufs, draws, vdata = [], [], bytearray()
    masks = dict(DEFAULT_MASKS)
    masks.update(model.get('vbuf_masks') or {})

    # skinned vertices: one buffer
    skin_bytes, skin_count = bytearray(), 0
    skin_draws = []
    for part in model.get('skin', []):
        for vnums, ltris, pal in _split_skin(part['verts'], part['tris']):
            first = skin_count
            for n in vnums:
                pos, uv, w, mirror, alpha = part['verts'][n]
                skin_bytes += _skin_vertex(pos, uv, w, mirror, alpha, pal)
            skin_count += len(vnums)
            idx = [first + i for t in ltris for i in t]
            skin_draws.append((part['material'], first, len(vnums), idx, pal,
                               [part['verts'][n][0] for n in vnums]))
    if skin_count:
        vbufs.append((SKIN_FORMAT, SKIN_STRIDE, masks[SKIN_FORMAT], skin_count, bytes(skin_bytes)))
        for mat, first, count, idx, pal, pts in skin_draws:
            draws.append(_draw_chunk(mat, model.get('draw_joint', 0), len(vbufs) - 1, first, count, idx, pal, pts))

    # rigid parts: a buffer per format, a draw per joint
    by_format = {}
    for part in model.get('rigid', []):
        by_format.setdefault(part['format'], []).append(part)
    for fmt, parts in by_format.items():
        data, count, pending = bytearray(), 0, []
        for part in parts:
            m = inv[part['joint']]
            first = count
            for pos, extra in part['verts']:
                p = character.apply(m, pos)
                if fmt == 0x07:
                    data += struct.pack('<3fI', *p, pack_normal(_rotate(m, extra)))
                else:
                    data += struct.pack('<3f4B', *p, *extra)
            count += len(part['verts'])
            idx = [first + i for t in part['tris'] for i in t]
            pending.append((part['material'], part['joint'], first, len(part['verts']), idx,
                            [v[0] for v in part['verts']]))
        vbufs.append((fmt, RIGID_STRIDE[fmt], masks.get(fmt, 0), count, bytes(data)))
        for mat, joint, first, n, idx, pts in pending:
            draws.append(_draw_chunk(mat, joint, len(vbufs) - 1, first, n, idx, None, pts))

    # vertex buffer descriptors (offsets relative to this model's vertex data; rebased by the caller)
    entries = bytearray()
    for fmt, stride, mask, count, data in vbufs:
        vdata += b'\0' * (-len(vdata) % 32)
        entries += struct.pack('<4BII4I', fmt, stride, stride, 8, mask, count, 0, 1, len(vdata), 0)
        vdata += data
    chunks.append(struct.pack('<III', 0x16, 12 + len(entries), len(vbufs)) + bytes(entries))
    chunks += model.get('extra', [])
    chunks += draws
    chunks.append(struct.pack('<III', 0x0D, 12, 0))
    chunks.append(END)
    return b''.join(chunks), bytes(vdata)


def _rigid_inverse(m):
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    t = [m[i][3] for i in range(3)]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    ti = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [rt[0] + [ti[0]], rt[1] + [ti[1]], rt[2] + [ti[2]], [0, 0, 0, 1]]


def _rotate(m, n):
    return tuple(m[r][0] * n[0] + m[r][1] * n[1] + m[r][2] * n[2] for r in range(3))


def _rebase(chain, base):
    """Add `base` to the data offset of every vertex buffer descriptor of a model chain."""
    out = bytearray(chain)
    for off, t, size in alr.chain(out, 0):
        if t == 0x16:
            n = struct.unpack_from('<I', out, off + 8)[0]
            for i in range(n):
                e = off + 0xC + 0x1C * i + 0x14
                struct.pack_into('<I', out, e, struct.unpack_from('<I', out, e)[0] + base)
    return bytes(out)


# ---------------------------------------------------------------- file

def build(header, textures, models, anims, n_anim_runs=None):
    """The .alr bytes. Runs: animation runs 0..n_anim_runs-1 (missing ones are written empty), then the models."""
    n_anim = n_anim_runs if n_anim_runs is not None else (max(anims) + 1 if anims else 0)
    texs = [t if 'data' in t else encode_texture(t) for t in textures]

    rb = bytearray()
    chains = []
    for i in range(n_anim):
        a = anims.get(i)
        chains.append(a if isinstance(a, (bytes, bytearray)) else encode_run(a or []))
    for m in models:
        chain, vdata = model_chunks(m)
        rb += b'\0' * (-len(rb) % ALIGN)
        chains.append(_rebase(chain, len(rb)))
        rb += vdata
    tex_entries = bytearray()
    for t in texs:
        rb += b'\0' * (-len(rb) % ALIGN)
        tex_entries += _texture_entry(t, len(rb))
        rb += t['data']
    rb += b'\0' * (-len(rb) % ALIGN)

    n_runs = len(chains)
    head = bytearray(header[:0x20]) + bytearray(4 * n_runs)
    struct.pack_into('<I', head, 0, 0x11)
    struct.pack_into('<I', head, 0x04, len(head))
    struct.pack_into('<H', head, 0x08, 0x52)
    struct.pack_into('<H', head, 0x0A, 7)
    struct.pack_into('<HH', head, 0x10, n_runs, 0)
    meta = head + struct.pack('<III', 0x15, 12 + len(tex_entries), len(texs)) + tex_entries
    roots = []
    for c in chains:
        roots.append(len(meta))
        meta += c
    meta += b'\0' * (-len(meta) % 0x1000)
    struct.pack_into('<I', meta, 0x0C, len(meta))
    struct.pack_into('<I', meta, 0x14, len(rb))
    struct.pack_into('<%dI' % n_runs, meta, 0x20, *roots)
    return bytes(meta) + bytes(rb)
