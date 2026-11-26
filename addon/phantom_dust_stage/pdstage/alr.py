"""Reader for .alr containers (models, textures).

Layout from the Phantom Dust wiki (Modding/File Formats/ALR) and Torphedo's Esper-RE (src/formats/alr.h),
checked against the 2017 release. A file is a 0x11 header chunk, a 0x15 texture table, then chunk chains
(one per root/model), padding to 0x1000, and the "resource buffer" holding vertex and texture data.
Offsets into the resource buffer are relative to its start.
"""
import math
import struct

MAGIC = 0x11
NAME_CHARS = '\0' + '0123456789abcdefghijklmnopqrstuvwxyz_'

# Vertex formats (id -> size, uv offset, uv divisor, lightmap uv offset). Position is always 3 floats at 0.
VERTEX_FORMATS = {
    0x01: (0x18, 0x10, 4096, None), 0x03: (0x20, 0x10, 4096, None), 0x05: (0x1C, 0x10, 0x7FFF, None),
    0x07: (0x10, None, None, None), 0x08: (0x14, None, None, None), 0x09: (0x14, 0x0C, 4096, None),
    0x0B: (0x10, None, None, None), 0x10: (0x0C, None, None, None), 0x11: (0x18, 0x0C, 0x7FFF, None),
    0x15: (0x18, 0x0C, 0x7FFF, None), 0x16: (0x1C, 0x0C, 4096, None), 0x17: (0x20, 0x10, 4096, None),
    0x18: (0x10, None, None, None), 0x1A: (0x28, 0x10, 4096, None), 0x1D: (0x24, 0x10, 4096, None),
    0x1E: (0x1C, 0x10, 4096, None), 0x1F: (0x20, 0x10, 4096, 0x1C), 0x21: (0x20, 0x10, 4096, None),
    0x25: (0x1C, 0x10, 4096, None),
}

# Texture pixel formats (low 5 bits of the format byte) -> (name, DXGI format, block bytes or bytes/pixel)
PIXEL_FORMATS = {
    0x00: ('R8', 61, 1), 0x02: ('B5G5R5A1', 86, 2), 0x04: ('B4G4R4A4', 115, 2), 0x05: ('B5G6R5', 85, 2),
    0x06: ('B8G8R8A8', 87, 4), 0x12: ('B8G8R8A8', 87, 4), 0x28: ('B8G8R8A8', 87, 4),
    0x0C: ('BC1', 71, 8), 0x0E: ('BC2', 74, 16), 0x0F: ('BC3', 77, 16),
    0x13: ('R8', 61, 1), 0x1F: ('A8', 65, 1),
}


def _decode_word(w):
    chars = []
    for _ in range(6):
        r = w % 40
        w //= 40
        chars.append(NAME_CHARS[r] if r < len(NAME_CHARS) else '')
    return ''.join(reversed(chars))


def decode_text(*words):
    return ''.join(_decode_word(w) for w in words).replace('\0', '')


def header(b):
    magic, header_size, version_unk, rb_off, count, rb_size = struct.unpack_from('<IIIIII', b, 0)
    if magic != MAGIC:
        raise ValueError('not an .alr file (magic %#x)' % magic)
    roots = list(struct.unpack_from('<%dI' % count, b, 0x20))
    return dict(header_size=header_size, version=version_unk & 0xFFFF, resource_offset=rb_off,
                resource_size=rb_size, n_roots=count, roots=roots,
                # older names kept for tools/dump_alr.py
                flags=version_unk, meta_size=rb_off, data_size=rb_size)


def chain(b, off, limit=100000):
    """Records starting at a root offset: list of (offset, type, size). Ends with type 0."""
    out = []
    while off + 8 <= len(b) and len(out) < limit:
        t, s = struct.unpack_from('<2I', b, off)
        out.append((off, t, s))
        if t == 0 or s == 0:
            break
        off += s
    return out


def textures(b):
    """0x15 texture table: list of dicts (name, format, width, height, mips, offset, size, cubemap)."""
    h = header(b)
    off = h['header_size']
    cid, csize, n = struct.unpack_from('<3I', b, off)
    if cid != 0x15:
        return []
    out = []
    for i in range(n):
        e = off + 0xC + i * 0x1C
        _flags, rel, _unused, tflags, fmt, wpow, hpow, npot, n1, n2 = struct.unpack_from('<3I4BI2I', b, e)
        mips = wpow & 0xF
        if npot:
            w, hgt = (npot & 0xFFF) + 1, ((npot >> 12) & 0xFFF) + 1
        else:
            w, hgt = 1 << (wpow >> 4), 1 << (hpow & 0xF)
        out.append(dict(index=i, name=decode_text(n1, n2), format=fmt & 0x7F if fmt & 0x80 else fmt,
                        raw_format=fmt, width=w, height=hgt, mips=mips, offset=rel,
                        cubemap=bool(tflags & 4), npot=npot))
    order = sorted(range(n), key=lambda i: out[i]['offset'])
    for k, i in enumerate(order):
        nxt = out[order[k + 1]]['offset'] if k + 1 < n else h['resource_size']
        out[i]['size'] = nxt - out[i]['offset']
    return out


def texture_dds(b, t):
    """A texture as a .dds file (bytes), or None for formats not handled yet.
    Texture data in the 2017 release is linear (not Xbox-swizzled) and mip-mapped."""
    if t['cubemap']:
        return None
    name = PIXEL_FORMATS.get(t['format'], (None,))[0]
    w, h, mips = t['width'], t['height'], max(1, t['mips'])
    if name in ('B5G6R5', 'B5G5R5A1', 'B4G4R4A4'):
        return _dds16(b, t, name, w, h, mips)
    fourcc = {'BC1': b'DXT1', 'BC2': b'DXT3', 'BC3': b'DXT5'}.get(name)
    if fourcc:
        block = PIXEL_FORMATS[t['format']][2]
        top = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
        pf = struct.pack('<II4s5I', 32, 0x4, fourcc, 0, 0, 0, 0, 0)
        flags, pitch = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000, top
    elif name == 'B8G8R8A8':
        pf = struct.pack('<II4s5I', 32, 0x41, b'\0\0\0\0', 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        flags, pitch = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8, w * 4
    else:
        return None
    caps = 0x1000 | (0x400008 if mips > 1 else 0)
    hdr = struct.pack('<4s7I44x', b'DDS ', 124, flags, h, w, pitch, 0, mips) + pf + struct.pack('<4I4x', caps, 0, 0, 0)
    start = header(b)['resource_offset'] + t['offset']
    data = b[start:start + t['size']]
    if not fourcc and not t['raw_format'] & 0x80 and not t['npot']:
        # the original Xbox release: uncompressed textures are swizzled (format byte without the 0x80 the 2017
        # release sets on its linear ones; its compressed textures are the same bytes in both releases)
        data = unswizzle(data, w, h, mips, 4)
    return hdr + data


def texture_level_dds(b, t):
    """Every mip level of a texture as its own one-level .dds file (bytes), level 0 first (texture_dds split up:
    the game's lower levels are pictures of their own, pdstage/texlevels.py); [] when texture_dds can't read it."""
    full = texture_dds(b, t)
    if not full:
        return []
    fourcc = full[84:88]
    block = {b'DXT1': 8, b'DXT3': 16, b'DXT5': 16}.get(fourcc)
    data, pos, out = full[128:], 0, []
    w, h = t['width'], t['height']
    for _ in range(max(1, t['mips'])):
        n = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block if block else w * h * 4
        if pos + n > len(data):
            break
        hdr = bytearray(full[:128])
        struct.pack_into('<3I', hdr, 12, h, w, n if block else w * 4)
        struct.pack_into('<I', hdr, 28, 1)
        struct.pack_into('<I', hdr, 108, 0x1000)
        out.append(bytes(hdr) + data[pos:pos + n])
        pos += n
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def _dds16(b, t, name, w, h, mips):
    """A 16-bit texture (st01/st08's sky cloud colour cloud_color3 is R5G6B5) as a B8G8R8A8 .dds: each mip level
    expanded to 8 bits per channel (the Xbox release's are swizzled: un-swizzled first)."""
    from . import texlevels
    start = header(b)['resource_offset'] + t['offset']
    data = bytes(b[start:start + t['size']])
    swz = not t['raw_format'] & 0x80 and not t['npot']
    out, pos = bytearray(), 0
    for lw, lh in texlevels.level_dims(w, h, mips):
        if pos + 2 * lw * lh > len(data):
            break
        out += texlevels.decode_level(data[pos:pos + 2 * lw * lh], name.lower(), lw, lh, swz)[..., [2, 1, 0, 3]].tobytes()
        pos += 2 * lw * lh
    pf = struct.pack('<II4s5I', 32, 0x41, b'\0\0\0\0', 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x8
    caps = 0x1000 | (0x400008 if mips > 1 else 0)
    hdr = struct.pack('<4s7I44x', b'DDS ', 124, flags, h, w, w * 4, 0, mips) + pf + struct.pack('<4I4x', caps, 0, 0, 0)
    return hdr + bytes(out)


def _morton(w, h):
    """Swizzled position of every (x, y) of a power-of-two w x h texture: the bits of x and y interleaved from
    the lowest (x first) while both have bits, then the larger side's remaining bits."""
    import numpy as np
    xs, ys = np.arange(w, dtype=np.int64), np.arange(h, dtype=np.int64)
    ox, oy = np.zeros(w, dtype=np.int64), np.zeros(h, dtype=np.int64)
    bit, i = 0, 0
    while (1 << i) < max(w, h):
        if (1 << i) < w:
            ox |= ((xs >> i) & 1) << bit
            bit += 1
        if (1 << i) < h:
            oy |= ((ys >> i) & 1) << bit
            bit += 1
        i += 1
    return oy[:, None] + ox[None, :]


def unswizzle(data, w, h, mips, bpp):
    """Xbox swizzled texture data (mip levels one after another) -> linear rows."""
    import numpy as np
    out, pos = bytearray(), 0
    for _ in range(max(1, mips)):
        n = w * h * bpp
        level = np.frombuffer(bytes(data[pos:pos + n]), dtype=np.uint8)
        if len(level) < n:
            out += data[pos:]
            break
        px = level.reshape(-1, bpp)
        out += px[_morton(w, h).ravel()].tobytes()
        pos += n
        w, h = max(1, w // 2), max(1, h // 2)
    out += data[pos:]
    return bytes(out)


def skeleton(b, root_off):
    """Node list (record type 3) of one root: dicts with t, rot, scale, flags, id, parent.
    Entries are 64 bytes from record offset +16. Mesh records (type 2) name their node at +0x42."""
    c = chain(b, root_off)
    sk = [x for x in c if x[1] == 3]
    if not sk:
        return [], {}
    off, _, size = sk[0]
    nodes = _nodes(b, off, size)
    meshes_per_node = {}
    for o, t, _ in c:
        if t == 2:
            n = struct.unpack_from('<H', b, o + 0x42)[0]
            meshes_per_node[n] = meshes_per_node.get(n, 0) + 1
    return nodes, meshes_per_node


def _nodes(b, off, size):
    nodes = []
    for i in range((size - 16) // 64):
        e = off + 16 + i * 64
        f = struct.unpack_from('<9f', b, e)
        flags, nid, _unk, parent = struct.unpack_from('<4H', b, e + 36)
        nodes.append(dict(t=f[0:3], rot=f[3:6], scale=f[6:9], flags=flags, id=nid,
                          parent=None if parent == 0xFFFF else parent,
                          values=struct.unpack_from('<4f', b, e + 0x30),     # per-node values objects read
                          marker=struct.unpack_from('<I', b, e + 0x2C)[0]))  # STAY_MARKER: piece stays put
    return nodes


def _materials(b, off):
    n = struct.unpack_from('<H', b, off + 8)[0]
    out = []
    for i in range(n):
        e = off + 0xC + i * 0x4C
        t1, t2 = struct.unpack_from('<2I', b, e)
        vfmt, vsize = struct.unpack_from('<2B', b, e + 0x10)
        tex = struct.unpack_from('<4H', b, e + 0x18)
        out.append(dict(shader=decode_text(t1, t2), vertex_format=vfmt, vertex_size=vsize,
                        textures=[None if t == 0xFFFF else t for t in tex], raw=b[e:e + 0x4C]))
    return out


def _vertex_buffers(b, off):
    n = struct.unpack_from('<I', b, off + 8)[0]
    out = []
    for i in range(n):
        e = off + 0xC + i * 0x1C
        fmt, vsize, vsize2, _u = struct.unpack_from('<4B', b, e)
        mask, count = struct.unpack_from('<2I', b, e + 4)
        rel = struct.unpack_from('<I', b, e + 0x14)[0]
        out.append(dict(format=fmt, vertex_size=vsize, count=count, offset=rel, mask=mask))
    return out


def meshes(b, root_off):
    """Meshes (0x02 records) of one root with the material, node list and vertex buffer they use."""
    mats, nodes, vbufs, out = [], [], [], []
    for off, t, size in chain(b, root_off):
        if t == 0x01:
            mats = _materials(b, off)
        elif t == 0x03:
            nodes = _nodes(b, off, size)
        elif t == 0x16:
            vbufs = _vertex_buffers(b, off)
        elif t == 0x02:
            center = struct.unpack_from('<3f', b, off + 0x08)
            mat, node, vb, prim = struct.unpack_from('<4H', b, off + 0x40)
            first, ntri, nidx = struct.unpack_from('<3I', b, off + 0x48)
            idx = list(struct.unpack_from('<%dH' % nidx, b, off + 0x68))
            box = (struct.unpack_from('<3f', b, off + 0x18), struct.unpack_from('<3f', b, off + 0x24))
            out.append(dict(offset=off, center=center, box=box, material=mat, node=node, vbuf=vb, primitive=prim,
                            first=first, ntri=ntri, indices=idx, materials=mats, nodes=nodes, vbufs=vbufs))
    return out


def triangles_from_indices(idx, primitive):
    """List of index triples. 5 = triangle list, 6 = strip (degenerate triangles dropped)."""
    if primitive == 5:
        return [tuple(idx[i:i + 3]) for i in range(0, len(idx) - 2, 3)]
    tris = []
    for i in range(len(idx) - 2):
        a, b_, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b_ or b_ == c or a == c:
            continue
        tris.append((a, b_, c) if i % 2 == 0 else (b_, a, c))
    return tris


def read_vertices(b, rb_off, vb):
    """Positions and UVs of a vertex buffer: (positions, uvs, lightmap_uvs)."""
    fmt = VERTEX_FORMATS.get(vb['format'])
    size = vb['vertex_size']
    base = rb_off + vb['offset']
    pos, uv, uv2 = [], [], []
    for i in range(vb['count']):
        v = base + i * size
        pos.append(struct.unpack_from('<3f', b, v))
        if fmt and fmt[1] is not None:
            u, w = struct.unpack_from('<2h', b, v + fmt[1])
            uv.append((u / fmt[2], w / fmt[2]))
        if fmt and fmt[3] is not None:
            u, w = struct.unpack_from('<2h', b, v + fmt[3])
            uv2.append((u / fmt[2], w / fmt[2]))
    return pos, uv, uv2


# Baked vertex colour (bytes B, G, R, A) per vertex format: the lighting the game multiplies the texture by.
# Confirmed for these formats on st04; others not checked yet.
COLOUR_AT = {0x01: 0x14, 0x03: 0x14, 0x09: 0x10}


def attribute_offsets(mask):
    """{attribute bit: byte offset in the vertex} for a vertex-buffer attribute mask: bits 0-2 are the position
    (12 bytes at 0), every other set bit adds 4 bytes in ascending bit order (clean-room notes on the ALR format,
    "Vertex attributes": all 19 format / mask pairs of the game's files fit stride = 12 + 4 x bits)."""
    out, off, bit = {}, 12, 8
    while bit <= mask:
        if mask & bit:
            out[bit] = off
            off += 4
        bit <<= 1
    return out


def unpack_normal(w):
    """A packed normal (11, 11, 10 signed bits: x, y, z), the inverse of alr_build.pack_normal."""
    s = lambda v, bits: v - (1 << bits) if v & (1 << (bits - 1)) else v
    return (s(w & 0x7FF, 11) / 1023.0, s((w >> 11) & 0x7FF, 11) / 1023.0, s((w >> 22) & 0x3FF, 10) / 511.0)


def read_normals(b, rb_off, vb):
    """Per-vertex normals (bit 0x08 of the buffer's mask), or None if the format has none."""
    at = attribute_offsets(vb.get('mask', 0)).get(0x08)
    if at is None:
        return None
    base, size = rb_off + vb['offset'] + at, vb['vertex_size']
    return [unpack_normal(struct.unpack_from('<I', b, base + i * size)[0]) for i in range(vb['count'])]


def read_colours(b, rb_off, vb):
    """Per-vertex (r, g, b, a) bytes (bit 0x80 of the buffer's mask), or None if the format has no colour."""
    at = attribute_offsets(vb.get('mask', 0)).get(0x80, COLOUR_AT.get(vb['format']))
    if at is None:
        return None
    base, size = rb_off + vb['offset'] + at, vb['vertex_size']
    out = []
    for i in range(vb['count']):
        c = b[base + i * size:base + i * size + 4]
        out.append((c[2], c[1], c[0], c[3]))
    return out


def node_matrix(nodes, i):
    """World matrix (row-major 4x4 nested lists) of node i: T * Rz * Ry * Rx * S, times its parents."""
    m = _identity()
    seen = 0
    while i is not None and i < len(nodes) and seen < 256:
        n = nodes[i]
        m = _mul(_local(n), m)
        i = n['parent']
        seen += 1
    return m


def _identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _local(n):
    rx, ry, rz = n['rot']
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = [[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]]
    Ry = [[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]]
    Rz = [[cz, -sz, 0, 0], [sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    S = [[n['scale'][0], 0, 0, 0], [0, n['scale'][1], 0, 0], [0, 0, n['scale'][2], 0], [0, 0, 0, 1]]
    T = [[1, 0, 0, n['t'][0]], [0, 1, 0, n['t'][1]], [0, 0, 1, n['t'][2]], [0, 0, 0, 1]]
    return _mul(T, _mul(Rz, _mul(Ry, _mul(Rx, S))))


def apply(m, v):
    return tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3))
