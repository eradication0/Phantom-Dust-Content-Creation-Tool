"""Write a stage .alr: replace models (roots) of a game original's .alr with new meshes and textures.

The file is rebuilt from its parts: the 0x11 header (root offsets updated), the 0x15 texture table (new
entries appended), every root's chunk chain (replaced roots rebuilt, the rest copied unchanged), zero
padding to 0x1000, then the resource buffer: the base buffer unchanged with the new vertex and texture data
appended. Offsets into the resource buffer are relative to its start, so the base data keeps working.

New meshes use one of the game's four stage shaders (see MATERIAL_TEMPLATES), picked from the maps they use:
  sd        texture x baked light, sun highlight                      vertex format 0x01 (0x18 bytes)
  sbts      + normal map                                              vertex format 0x03 (0x20 bytes)
  sdrefs    + reflection (sphere) map                                 vertex format 0x01
  sbtsrefs  + normal map and reflection map                           vertex format 0x03
Format 0x01: position, packed normal, UV (/4096), BGRA colour (RGB = baked light, A = shine mask).
Format 0x03: the same, then packed tangent and binormal (same 11/11/10 packing as the normal).
  lbts      texture x (ambient + light map), light-mapped              vertex format 0x1F (0x20 bytes)
Format 0x1F (the underground hub's, works on battle stages): position, packed normal, UV0 (u16 / 4096, 0-16),
packed tangent and binormal, UV1 (u16 / 4096) for the light map. No vertex colour. Material slots: diffuse,
light map, normal map (FORMATS.md, "Light maps").
Mesh and vertex-buffer fields not understood are copied from an existing "sd" mesh in the base file.
New textures are uncompressed BGRA (format 0x86) with a full mip chain.
"""
import math
import struct

from . import alr
from .collision_build import enclosing_sphere

FORMAT = 0x01
VERTEX_SIZE = 0x18
BUMP_FORMAT = 0x03
BUMP_VERTEX_SIZE = 0x20
# Xbox-era attribute mask stored in vertex-buffer entries (+0x04): position, normal, UV, colour (+ tangent, binormal)
LM_FORMAT = 0x1F
LM_VERTEX_SIZE = 0x20
VERTEX_MASK = {FORMAT: 0x00CF, BUMP_FORMAT: 0x30CF, 0x09: 0x00C7, 0x0B: 0x0087, LM_FORMAT: 0x0010304F}
# the hub's (st09_01) lbts material entry: slots diffuse, light map, normal map; roles 0x0261
LBTS_TEMPLATE = ('40c1398800000000000000002d0000001f102600001161021c00230013000000000000000000000000000000000000000000'
                 '00ff7f7f7f140000000000000000000000000000000000000000')

# Material entries (0x4C bytes) copied from the game's own maps (st04 sd/sbts/sbtsrefs, st05 sdrefs). Fields set
# by material_record: +0x0C flags, +0x10 vertex format, +0x12 index, +0x16 texture-slot roles, +0x18 texture
# indices, +0x34 specular. Everything else is kept as the game has it.
MATERIAL_TEMPLATES = {
    'sd': '006023b300000000000000000900000001100e0000110100160000000000000000000000000000000000000000000000000000'
          'ff000000000000000000000000000000000000000000000000',
    'sbts': '4041f3b200000000000000002d0000000310000000112100000001000000000000000000000000000000000000000000000000'
            'ff5353530f0000000000000000000000000000000000000000',
    'sdrefs': '5d183fb300000000000000000d4400000111020000114100000002000000000000000000000000000000000000000000000000'
              'ffffffff500000000000000000000000000000000000000000',
    'sbtsrefs': 'af45f3b200d01466000000002d04000003101600001121041c001d001e00000000000000000000000000000000000000000000'
                'ffffffff02000000000000000032000000640064000a000000',
}
# texture-slot role nibbles at +0x16 (1 diffuse, 2 normal map, 4 reflection map) and which map fills each slot
SLOT_ROLES = {'sd': (0x0001, ('d',)), 'sbts': (0x0021, ('d', 'n')), 'sdrefs': (0x0041, ('d', 'r')),
              'sbtsrefs': (0x0421, ('d', 'n', 'r'))}


def shader_for(normal, reflection):
    return {(False, False): 'sd', (True, False): 'sbts', (False, True): 'sdrefs', (True, True): 'sbtsrefs'}[
        (bool(normal), bool(reflection))]


def lbts_record(index, diffuse, lightmap, normal, specular=(0, 0, 0, 0)):
    """A light-mapped material entry (shader lbts): absolute texture indices; normal is required (the hub
    uses a 4 x 4 flat normal texture where there is none)."""
    raw = bytearray(bytes.fromhex(LBTS_TEMPLATE))
    r, g, b, power = (int(max(0, min(255, round(x)))) for x in specular)
    spec_on = (r or g or b) and power > 0
    raw[0x12] = index & 0xFF
    struct.pack_into('<4H', raw, 0x18, diffuse, lightmap, normal, diffuse)
    struct.pack_into('<4B', raw, 0x34, b, g, r, power if spec_on else 0x14)
    return bytes(raw)


def material_record(kind, index, diffuse, normal=None, reflection=None, specular=(0, 0, 0, 0)):
    """One 0x4C-byte material entry for a stage shader.

    kind: 'sd', 'sbts', 'sdrefs' or 'sbtsrefs'. diffuse/normal/reflection: absolute texture-table indices.
    specular: (r, g, b, power) bytes; the game adds colour * (N.H)^power on top of the lit texture (shine
    mask = vertex alpha). Colour (0, 0, 0) = no highlight, as on most of the game's own surfaces."""
    raw = bytearray(bytes.fromhex(MATERIAL_TEMPLATES[kind]))
    r, g, b, power = (int(max(0, min(255, round(x)))) for x in specular)
    spec_on = (r or g or b) and power > 0
    bump = kind in ('sbts', 'sbtsrefs')
    raw[0x0C] = (0x29 if bump else 0x09) | (0x04 if spec_on else 0)
    raw[0x0D] = 0x04 if kind.endswith('refs') else 0x00
    raw[0x10] = BUMP_FORMAT if bump else FORMAT
    raw[0x11] = 0x10
    raw[0x12] = index & 0xFF
    raw[0x13] = 0
    roles, slots = SLOT_ROLES[kind]
    struct.pack_into('<H', raw, 0x16, roles)
    by = dict(d=diffuse, n=normal, r=reflection)
    tex = [by[s] for s in slots]
    tex += [diffuse] * (4 - len(tex))                        # the game fills unused slots with some texture too
    struct.pack_into('<4H', raw, 0x18, *tex)
    struct.pack_into('<4B', raw, 0x30, 0, 0, 0, 0xFF)
    struct.pack_into('<4B', raw, 0x34, b, g, r, power if spec_on else 0)
    return bytes(raw)
UV_DIV = 4096
MAX_VERTS = 0xFFFF
TEX_FORMAT = 0x86
ALIGN = 0x100
NAME_CHARS = '0123456789abcdefghijklmnopqrstuvwxyz'


# ---------------------------------------------------------------- small encoders

def encode_word(text):
    v = 0
    for c in (text + '\0' * 6)[:6]:
        c = c.lower()
        if c.isdigit():
            k = 1 + ord(c) - ord('0')
        elif 'a' <= c <= 'z':
            k = 11 + ord(c) - ord('a')
        elif c in ' _-':
            k = 37
        else:
            k = 0
        v = v * 40 + k
    return v


def encode_text(text):
    return encode_word(text[:6]), encode_word(text[6:12])


def pack_normal(n):
    l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
    x, y, z = (c / l for c in n)
    q = lambda v, m, bits: int(round(max(-1.0, min(1.0, v)) * m)) & ((1 << bits) - 1)
    return q(x, 1023, 11) | (q(y, 1023, 11) << 11) | (q(z, 511, 10) << 22)


def _pad(data, align):
    return data + b'\0' * (-len(data) % align)


# ---------------------------------------------------------------- templates from the base file

def _templates(b):
    """Raw records of an existing format-0x01 "sd" mesh to copy unknown fields from."""
    h = alr.header(b)
    found = None
    prim5_unk = None
    for r in h['roots']:
        mats = vbs = None
        mat_hdr = None
        for off, t, size in alr.chain(b, r):
            if t == 0x01:
                mats = alr._materials(b, off)
                mat_hdr = b[off:off + 12]
            elif t == 0x16:
                vbs = (off, alr._vertex_buffers(b, off))
            elif t == 0x02 and mats and vbs:
                mat_i, _node, vb_i, prim = struct.unpack_from('<4H', b, off + 0x40)
                if prim == 5 and prim5_unk is None:
                    prim5_unk = b[off + 0x30:off + 0x40]
                if found is None and mat_i < len(mats) and vb_i < len(vbs[1]):
                    m = mats[mat_i]
                    if m['shader'] == 'sd' and m['vertex_format'] == FORMAT and vbs[1][vb_i]['format'] == FORMAT:
                        found = dict(material=bytearray(m['raw']), material_hdr=bytes(mat_hdr),
                                     vbuf=bytearray(b[vbs[0] + 0xC + vb_i * 0x1C:vbs[0] + 0xC + (vb_i + 1) * 0x1C]),
                                     mesh=bytearray(b[off:off + 0x68]), mesh_prim=prim)
    if found is None:
        raise ValueError('base .alr has no "sd" format-0x01 mesh to copy settings from')
    if prim5_unk is not None:
        found['mesh'][0x30:0x40] = prim5_unk          # fields that go with triangle-list meshes
    # The stage's shadow mesh (shader sshadowch, vertex format 0x07): without it characters cast no shadow.
    found['shadow'] = None
    for r in h['roots']:
        mats = None
        for off, t, size in alr.chain(b, r):
            if t == 0x01:
                mats = alr._materials(b, off)
            elif t == 0x02 and mats and found['shadow'] is None:
                mat_i = struct.unpack_from('<H', b, off + 0x40)[0]
                if mat_i < len(mats) and mats[mat_i]['shader'] == 'sshadowch':
                    found['shadow'] = dict(material=bytes(mats[mat_i]['raw']), header=bytes(b[off:off + 0x68]))
    tex = [t for t in alr.textures(b)]
    t86 = next((t for t in tex if t['raw_format'] == TEX_FORMAT), None)
    hoff = h['header_size']
    found['texture'] = bytearray(b[hoff + 0xC + t86['index'] * 0x1C:hoff + 0xC + (t86['index'] + 1) * 0x1C]) if t86 else \
        bytearray(struct.pack('<3I4BI2I', 0x00040001, 0, 0, 0x29, TEX_FORMAT, 0, 0, 0, 0, 0))
    return found


def _empty_chain(b):
    """An existing empty root chain (no meshes), to clear a model."""
    for r in alr.header(b)['roots']:
        c = alr.chain(b, r)
        if not any(t == 0x02 for _, t, _ in c):
            return bytes(b[r:c[-1][0] + c[-1][2]])
    return (struct.pack('<IIHH', 1, 12, 0, 0x41) + struct.pack('<IIHHI', 3, 16, 0, 0, 0)
            + struct.pack('<III', 0x16, 12, 0) + struct.pack('<III', 0xD, 12, 0) + struct.pack('<II', 0, 8))


# ---------------------------------------------------------------- building a model

def texture_record(tpl, name, width, height, mips, rel_offset, fmt=TEX_FORMAT):
    """fmt: TEX_FORMAT (plain BGRA), 0x0C DXT1 or 0x0F DXT5 (pdstage/dxt.py), as the game's own textures."""
    e = bytearray(tpl)
    wp, hp = width.bit_length() - 1, height.bit_length() - 1
    struct.pack_into('<I', e, 0x04, rel_offset)
    struct.pack_into('<4B', e, 0x0C, e[0x0C], fmt, (wp << 4) | (mips & 0xF), hp & 0xF)
    struct.pack_into('<I', e, 0x10, 0)
    struct.pack_into('<2I', e, 0x14, *encode_text(name))
    return bytes(e)


def split_mesh(verts, tris, limit=MAX_VERTS):
    """Split (verts, tris) into parts that each use at most `limit` vertices."""
    if len(verts) <= limit:
        return [(verts, tris)]
    parts, cur, remap = [], [], {}
    for t in tris:
        new = [i for i in t if i not in remap]
        if len(remap) + len(new) > limit:
            parts.append(([verts[i] for i in sorted(remap, key=remap.get)], cur))
            cur, remap = [], {}
        for i in t:
            remap.setdefault(i, len(remap))
        cur.append(tuple(remap[i] for i in t))
    if cur:
        parts.append(([verts[i] for i in sorted(remap, key=remap.get)], cur))
    return parts


SHADOW_FORMAT = 0x07
SHADOW_VERTEX_SIZE = 0x10


def _box(centre, size):
    """Closed box, outward-facing triangles: (verts [(pos, normal)], tris)."""
    cx, cy, cz = centre
    s = size / 2
    corner = lambda i: (cx + (s if i & 1 else -s), cy + (s if i & 2 else -s), cz + (s if i & 4 else -s))
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    verts, tris = [], []
    for q in quads:
        a, b_, c, d = (corner(i) for i in q)
        u = [b_[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        base = len(verts)
        verts += [(p, n) for p in (a, b_, c, d)]
        tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return verts, tris


def shadow_meshes(tpl, meshes, mode='minimal'):
    """Shadow mesh for a stage, using the game original's sshadowch material (vertex format 0x07).

    The game needs one for characters to cast shadows. In the original maps it holds shadow volumes of the
    stage (closed shapes the game darkens what falls inside), so a plain copy of the stage looks wrong.
    mode 'minimal': a 1-unit closed box far below the stage: turns character shadows on, adds no stage shadows.
    mode 'full': every triangle of the meshes (for experiments; draws badly in game).
    Returns raw mesh dicts for build_model (empty if the game original has no shadow mesh)."""
    if not tpl.get('shadow'):
        return []
    index, verts, tris = {}, [], []
    if mode == 'minimal':
        pts = [m['verts'][i][0] for m in meshes if 'raw' not in m for t in m['tris'] for i in t]
        if not pts:
            return []
        lo = [min(p[k] for p in pts) for k in range(3)]
        hi = [max(p[k] for p in pts) for k in range(3)]
        box_v, box_t = _box(((lo[0] + hi[0]) / 2, lo[1] - 1000.0, (lo[2] + hi[2]) / 2), 1.0)
        verts = [(p, pack_normal(n)) for p, n in box_v]
        tris = box_t
        meshes = []
    for m in meshes:
        if 'raw' in m:
            continue
        for t in m['tris']:
            out = []
            for i in t:
                pos, nrm = m['verts'][i][0], m['verts'][i][1]
                key = (tuple(round(c, 3) for c in pos), pack_normal(nrm))
                if key not in index:
                    index[key] = len(verts)
                    verts.append(key)
                out.append(index[key])
            tris.append(tuple(out))
    result = []
    for part_verts, part_tris in split_mesh(verts, tris):
        data = b''.join(struct.pack('<3fI', *p, n) for p, n in part_verts)
        result.append(dict(raw=dict(material=tpl['shadow']['material'], format=SHADOW_FORMAT,
                                    vertex_size=SHADOW_VERTEX_SIZE, vertex_bytes=data, tris=part_tris,
                                    header=tpl['shadow']['header'])))
    return result


STAY_MARKER = 0x4B085FC0     # node +0x2C: a broken model's piece that stays where it is (no physics)


def game_mass(lo, hi):
    """How heavy the game makes a breaking piece or debris body (pdStageObjRoll, FUN_1401f7dd0): the volume of its
    mesh box in game units. The launch speed is sqrt(1200 / max(mass, 200)), at most 1.5 units per frame, so
    anything lighter than about 530 flies at full speed."""
    v = 1.0
    for k in range(3):
        v *= abs(hi[k] - lo[k])
    return v


def box_for_mass(lo, hi, mass):
    """The box (lo, hi) scaled about its centre so game_mass gives `mass`. The game also uses this box as the
    body's collision shape (shrunk by 15% on each side along axes longer than 5)."""
    have = game_mass(lo, hi)
    if mass <= 0 or have <= 0:
        return list(lo), list(hi)
    f = (mass / have) ** (1.0 / 3.0)
    mid = [(lo[k] + hi[k]) / 2 for k in range(3)]
    return [mid[k] - (mid[k] - lo[k]) * f for k in range(3)], [mid[k] + (hi[k] - mid[k]) * f for k in range(3)]


def node_record(t=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), flags=0x0004, parent=None, values=(0, 0, 0, 0), node_id=0,
                marker=0xFFFFFFFF):
    """One 64-byte node: transform, flags, id, parent (None = root), marker and four per-node values.
    The game reads them when an object breaks (FORMATS.md, objects): a broken model's pieces are the root's
    children; a piece's first value non-zero = it can hit players while flying; marker STAY_MARKER = the piece
    stays in place. Debris roots: (2, 2) = goes away. Stage models use zeros."""
    return struct.pack('<9fHHHHI4f', *t, *rot, *scale, flags, node_id, 0, 0xFFFF if parent is None else parent,
                       marker, *values)


def build_model(tpl, meshes, texture_base_index, rb_base, nodes=None, material_unk=None):
    """Chunk chain for one root plus its vertex data.

    meshes: list of dict(verts=[(pos, normal, uv) or (pos, normal, uv, (r, g, b, a)[, tangent, binormal])],
            tris=[(a, b, c)], node=..., and either
              material=dict(diffuse=ref, normal=ref or None, reflection=ref or None, specular=(r, g, b, power)),
                where a ref is ('base', index into the base texture table) or ('new', index into the new textures);
                a normal map needs a tangent and binormal on every vertex,
            or the older texture=index into the new textures / texture_index=an existing base entry (shader sd,
            no highlight). The colour (0-255) is RGB = baked light the game multiplies the texture by, A = shine
            mask (how much of the specular highlight and reflection shows); white if missing.
            A mesh can instead be dict(raw=...) to carry an existing mesh over unchanged in format (see raw_mesh).
    Returns (chain bytes, vertex data bytes appended at rb_base, stats)."""
    mat_index, materials = {}, []
    parts = []
    # node dicts may carry box=(lo, hi): written as the box of every mesh on that node (game_mass)
    boxes = {k: n['box'] for k, n in enumerate(nodes or ()) if isinstance(n, dict) and n.get('box')}
    nodes = None if nodes is None else [{x: v for x, v in n.items() if x != 'box'} if isinstance(n, dict) else n
                                        for n in nodes]

    def absolute(ref):
        if ref is None:
            return None
        kind, i = ref
        return i if kind == 'base' else texture_base_index + i

    for m in meshes:
        if 'raw' in m:
            r = m['raw']
            over = tuple(sorted((r.get('tex_override') or {}).items()))
            key = ('raw', r['material'], over)
            if key not in mat_index:
                mat_index[key] = len(materials)
                raw = bytearray(r['material'])
                raw[0x12] = len(materials) & 0xFF
                for slot, ref in over:                    # e.g. a new cloud texture in slot 0
                    struct.pack_into('<H', raw, 0x18 + 2 * slot, absolute(ref))
                materials.append(bytes(raw))
            parts.append((mat_index[key], r, r['tris'], m.get('node', 0), False))
            continue
        if 'material' in m and m['material'].get('lightmap') is not None:   # light-mapped (lbts)
            md = m['material']
            d, lm, n = absolute(md['diffuse']), absolute(md['lightmap']), absolute(md['normal'])
            spec = tuple(md.get('specular', (0, 0, 0, 0)))
            key = ('lbts', d, lm, n, spec)
            if key not in mat_index:
                mat_index[key] = len(materials)
                materials.append(lbts_record(len(materials), d, lm, n, spec))
            if any(len(v) < 7 for v in m['verts']):
                raise ValueError('a light-mapped mesh needs tangent, binormal and a second UV on every vertex')
            for verts, tris in split_mesh(m['verts'], m['tris']):
                parts.append((mat_index[key], verts, tris, m.get('node', 0), 'lm'))
            continue
        if 'material' in m:
            md = m['material']
            d, n, rf = absolute(md['diffuse']), absolute(md.get('normal')), absolute(md.get('reflection'))
            spec = tuple(md.get('specular', (0, 0, 0, 0)))
        else:
            d = m['texture_index'] if 'texture_index' in m else texture_base_index + m['texture']
            n = rf = None
            spec = (0, 0, 0, 0)
        kind = shader_for(n is not None, rf is not None)
        key = (kind, d, n, rf, spec)
        if key not in mat_index:
            mat_index[key] = len(materials)
            materials.append(material_record(kind, len(materials), d, n, rf, spec))
        bump = n is not None
        if bump and any(len(v) < 6 for v in m['verts']):
            raise ValueError('a normal-mapped mesh needs a tangent and binormal on every vertex')
        for verts, tris in split_mesh(m['verts'], m['tris']):
            parts.append((mat_index[key], verts, tris, m.get('node', 0), bump))

    vdata = bytearray()
    vb_entries, mesh_chunks = [], []
    for i, (mi, verts, tris, node_i, bump) in enumerate(parts):
        pad = -(rb_base + len(vdata)) % ALIGN
        vdata += b'\0' * pad
        rel = rb_base + len(vdata)
        e = bytearray(tpl['vbuf'])
        if isinstance(verts, dict):                      # carried-over mesh: its own format and vertex bytes
            r = verts
            vdata += r['vertex_bytes']
            e[0], e[1], e[2] = r['format'], r['vertex_size'], r['vertex_size']
            if r['format'] in VERTEX_MASK:
                struct.pack_into('<I', e, 0x04, VERTEX_MASK[r['format']])
            n_verts = len(r['vertex_bytes']) // r['vertex_size']
            pts = [struct.unpack_from('<3f', r['vertex_bytes'], k * r['vertex_size']) for k in range(n_verts)]
        elif bump == 'lm':
            for vert in verts:
                pos, nrm, uv = vert[:3]
                u, v = (int(max(0, min(65535, round(x * UV_DIV)))) for x in uv)
                u1, v1 = (int(max(0, min(65535, round(x * UV_DIV)))) for x in vert[6])
                vdata += struct.pack('<3fIHHIIHH', *pos, pack_normal(nrm), u, v, pack_normal(vert[4]),
                                     pack_normal(vert[5]), u1, v1)
            e[0], e[1], e[2] = LM_FORMAT, LM_VERTEX_SIZE, LM_VERTEX_SIZE
            struct.pack_into('<I', e, 0x04, VERTEX_MASK[LM_FORMAT])
            n_verts = len(verts)
            pts = [vert[0] for vert in verts]
        else:
            for vert in verts:
                pos, nrm, uv = vert[:3]
                col = vert[3] if len(vert) > 3 and vert[3] is not None else (255, 255, 255, 255)
                u = int(round(uv[0] * UV_DIV))
                v = int(round(uv[1] * UV_DIV))
                vdata += struct.pack('<3fIhh4B', *pos, pack_normal(nrm), max(-32768, min(32767, u)),
                                     max(-32768, min(32767, v)), col[2], col[1], col[0], col[3])
                if bump:
                    vdata += struct.pack('<2I', pack_normal(vert[4]), pack_normal(vert[5]))
            fmt, size = (BUMP_FORMAT, BUMP_VERTEX_SIZE) if bump else (FORMAT, VERTEX_SIZE)
            e[0], e[1], e[2] = fmt, size, size
            struct.pack_into('<I', e, 0x04, VERTEX_MASK[fmt])
            n_verts = len(verts)
            pts = [vert[0] for vert in verts]
        struct.pack_into('<I', e, 0x08, n_verts)
        struct.pack_into('<I', e, 0x14, rel)
        vb_entries.append(bytes(e))

        centre, _ = enclosing_sphere(pts)
        radius = max(math.dist(centre, p) for p in pts)
        idx = [i for t in tris for i in t]
        hdr = bytearray(verts['header'] if isinstance(verts, dict) and 'header' in verts else tpl['mesh'])
        struct.pack_into('<3ff', hdr, 0x08, *centre, radius)
        lo, hi = boxes.get(node_i) or ([min(p[k] for p in pts) for k in range(3)],
                                        [max(p[k] for p in pts) for k in range(3)])
        struct.pack_into('<3f', hdr, 0x18, *lo)       # box: for an object piece also its physics box and mass
        struct.pack_into('<3f', hdr, 0x24, *hi)
        struct.pack_into('<4H', hdr, 0x40, mi, node_i, i, 5)
        struct.pack_into('<3I', hdr, 0x48, min(idx), len(tris), len(idx))
        body = _pad(bytes(hdr[8:]) + struct.pack('<%dH' % len(idx), *idx), 4)
        mesh_chunks.append(struct.pack('<II', 0x02, 8 + len(body)) + body)

    chain = bytearray()
    unk = struct.unpack_from('<H', tpl['material_hdr'], 0x0A)[0] if material_unk is None else material_unk
    chain += struct.pack('<IIHH', 0x01, 12 + 0x4C * len(materials), len(materials), unk) + b''.join(materials)
    if nodes is None:
        node_bytes = struct.pack('<9fHHHHI16x', 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0xFFFF, 0xFFFFFFFF)
        n_nodes = 1
    else:
        node_bytes = b''.join(n if isinstance(n, (bytes, bytearray)) else node_record(node_id=k, **n)
                              for k, n in enumerate(nodes))           # bytes = an original node, as is
        n_nodes = len(nodes)
    chain += struct.pack('<IIHHI', 0x03, 16 + len(node_bytes), n_nodes, 0, 0) + node_bytes
    chain += struct.pack('<III', 0x16, 12 + 0x1C * len(vb_entries), len(vb_entries)) + b''.join(vb_entries)
    chain += b''.join(mesh_chunks)
    chain += struct.pack('<III', 0x0D, 12, 0) + struct.pack('<II', 0x00, 8)
    stats = dict(meshes=len(parts), materials=len(materials), triangles=sum(len(p[2]) for p in parts))
    return bytes(chain), bytes(vdata), stats


def raw_mesh(b, mesh, rb_off, apply_node=True):
    """Carry an existing mesh (e.g. a shadow mesh) into a rebuilt model: its material record, vertex format
    and bytes, with node transforms applied to the positions (the rebuilt model has one identity node).
    apply_node=False keeps the vertices as stored and the mesh on its own node (for models rebuilt with the
    original node list, like the sky)."""
    vb = mesh['vbufs'][mesh['vbuf']]
    size = vb['vertex_size']
    start = rb_off + vb['offset']
    data = bytearray(b[start:start + vb['count'] * size])
    mtx = alr.node_matrix(mesh['nodes'], mesh['node']) if apply_node and mesh['node'] < len(mesh['nodes']) else None
    if mtx:
        for k in range(vb['count']):
            p = struct.unpack_from('<3f', data, k * size)
            struct.pack_into('<3f', data, k * size, *alr.apply(mtx, p))
    tris = alr.triangles_from_indices(mesh['indices'], mesh['primitive'])
    out = dict(raw=dict(material=bytes(mesh['materials'][mesh['material']]['raw']), format=vb['format'],
                        vertex_size=size, vertex_bytes=bytes(data), tris=tris,
                        header=bytes(b[mesh['offset']:mesh['offset'] + 0x68])))
    if not apply_node:
        out['node'] = mesh['node']
    return out


# ---------------------------------------------------------------- the whole file

def rebuild(b, replace=None, textures=(), clear=(), shadows_for=(), shadow_mode='minimal', add_models=()):
    """New .alr bytes.

    replace:     {root index: list of meshes} (see build_model); texture indices refer to `textures`.
    textures:    list of dict(name, width, height, levels=[bytes per mip, top row first], format=TEX_FORMAT): plain
                 BGRA by default, or format 0x0C / 0x0F with DXT1 / DXT5 blocks (pdstage/dxt.py).
    clear:       root indices to empty (e.g. remove the background).
    shadows_for: replaced roots that also get a shadow mesh made from their triangles (the stage, root 0,
                 needs one for characters to cast shadows).
    add_models:  lists of meshes appended as new roots (e.g. object models, in local space); their root
                 indices are len(original roots), len + 1, ... (returned in stats['added_roots']).
    With no arguments the result is byte-identical to the input."""
    replace = replace or {}
    h = alr.header(b)
    hsize, rb_off, rb_size = h['header_size'], h['resource_offset'], h['resource_size']
    t15 = struct.unpack_from('<3I', b, hsize)
    tex_entries = bytes(b[hsize + 0xC:hsize + 0xC + 0x1C * t15[2]])
    rb = bytearray(b[rb_off:rb_off + rb_size])
    tpl = _templates(b) if (replace or textures or add_models) else None
    stats = {}

    # new textures appended to the resource buffer and the table
    new_entries = []
    for t in textures:
        rb += b'\0' * (-len(rb) % ALIGN)
        rel = len(rb)
        for lvl in t['levels']:
            rb += lvl
        new_entries.append(texture_record(tpl['texture'], t['name'], t['width'], t['height'],
                                          t.get('mips', len(t['levels'])), rel, t.get('format', TEX_FORMAT)))
    n_tex = t15[2] + len(new_entries)
    tex_chunk = struct.pack('<III', 0x15, 0xC + 0x1C * n_tex, n_tex) + tex_entries + b''.join(new_entries)
    tex_chunk = tex_chunk + bytes(b[hsize + 0xC + 0x1C * t15[2]:hsize + t15[1]])   # keep any trailing bytes

    chains = []
    empty = _empty_chain(b) if clear else None
    for i, r in enumerate(h['roots']):
        if i in replace:
            model = replace[i]
            ms, nodes, unk = (list(model['meshes']), model.get('nodes'), model.get('material_unk')) \
                if isinstance(model, dict) else (list(model), None, None)
            if i in shadows_for:
                ms += shadow_meshes(tpl, ms, shadow_mode)
            chain, vdata, st = build_model(tpl, ms, t15[2], len(rb), nodes, unk)
            rb += vdata
            stats[i] = st
            chains.append(chain)
        elif i in clear:
            chains.append(empty)
        else:
            c = alr.chain(b, r)
            chains.append(bytes(b[r:c[-1][0] + c[-1][2]]))
    added = []
    for model in add_models:
        # a model is a list of meshes, or dict(meshes=[...], nodes=[node kwargs...]) with meshes using 'node'
        ms, nodes = (model['meshes'], model.get('nodes')) if isinstance(model, dict) else (model, None)
        chain, vdata, st = build_model(tpl, list(ms), t15[2], len(rb), nodes)
        rb += vdata
        added.append(len(chains))
        chains.append(chain)
    stats['added_roots'] = added

    # metadata layout: header (with room for every root offset), texture table, then the original chains in
    # the order of their offsets, then any added chains
    n_roots = len(chains)
    order = sorted(range(len(h['roots'])), key=lambda i: h['roots'][i]) + added
    head = bytearray(b[:0x20]) + bytearray(4 * n_roots)
    if not added:
        head = bytearray(b[:hsize])                      # unchanged: keep the original header bytes exactly
    struct.pack_into('<I', head, 0x04, len(head))
    struct.pack_into('<I', head, 0x10, n_roots)
    meta = head + tex_chunk
    roots = [0] * n_roots
    for i in order:
        roots[i] = len(meta)
        meta += chains[i]
    end_of_meta = len(meta)
    meta += b'\0' * (-len(meta) % 0x1000)
    if b[end_of_meta:rb_off] and len(meta) == rb_off:
        meta[end_of_meta:] = b[end_of_meta:rb_off]          # identical padding when nothing moved
    struct.pack_into('<I', meta, 0x0C, len(meta))
    struct.pack_into('<I', meta, 0x14, len(rb))
    struct.pack_into('<%dI' % len(roots), meta, 0x20, *roots)
    return bytes(meta) + bytes(rb), stats
