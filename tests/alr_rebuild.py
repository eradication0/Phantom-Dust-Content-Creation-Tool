"""Checks for pdstage.alr_build (plain Python, no Blender).

  python tests/alr_rebuild.py <Assets/Data/Map folder> [out_dir]

1. Rebuilding every map .alr with no changes gives the identical file.
2. st04: the stage model (root 0) rebuilt from its own meshes (positions with node transforms applied,
   decoded normals, UVs, same textures) reads back with the same triangles. Writes out_dir/st04_rebuilt.alr.
3. A new texture added to the table reads back with the right name, size and pixels.
"""
import glob
import math
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import alr, alr_build  # noqa: E402

maps = sys.argv[1]
out_dir = sys.argv[2] if len(sys.argv) > 2 else None
fails = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


# 1. identity rebuild
same = []
for p in sorted(glob.glob(os.path.join(maps, 'st[0-3][0-9].alr'))):
    b = open(p, 'rb').read()
    nb, _ = alr_build.rebuild(b)
    same.append((os.path.basename(p), nb == b))
check(all(s for _, s in same), 'unchanged rebuild is byte-identical for %d maps %s' % (len(same), [n for n, s in same if not s]))


# 2. stage from its own meshes
def decode_normal(u):
    sx = lambda v, bits: v - (1 << bits) if v & (1 << (bits - 1)) else v
    return (sx(u & 0x7FF, 11) / 1023.0, sx((u >> 11) & 0x7FF, 11) / 1023.0, sx((u >> 22) & 0x3FF, 10) / 511.0)


def world_triangles(b, root):
    h = alr.header(b)
    out = []
    for m in alr.meshes(b, h['roots'][root]):
        mat = m['materials'][m['material']]
        if mat['shader'].startswith('sshadow'):
            continue
        vb = m['vbufs'][m['vbuf']]
        pos, uv, _ = alr.read_vertices(b, h['resource_offset'], vb)
        mtx = alr.node_matrix(m['nodes'], m['node'])
        for t in alr.triangles_from_indices(m['indices'], m['primitive']):
            out.append((tuple(tuple(round(c, 2) for c in alr.apply(mtx, pos[i])) for i in t),
                        tuple(tuple(round(c, 3) for c in uv[i]) for i in t) if uv else None, mat['textures'][0]))
    return out


b = open(os.path.join(maps, 'st04.alr'), 'rb').read()
h = alr.header(b)
COLOUR_AT = {0x01: 0x14, 0x03: 0x14, 0x09: 0x10}       # baked vertex colour (B, G, R, A bytes)


def colours(b, root):
    h = alr.header(b)
    out = Counter()
    for m in alr.meshes(b, h['roots'][root]):
        vb = m['vbufs'][m['vbuf']]
        at = COLOUR_AT.get(vb['format'])
        if at is None:
            continue
        base = h['resource_offset'] + vb['offset']
        for i in sorted({i for t in alr.triangles_from_indices(m['indices'], m['primitive']) for i in t}):
            out[b[base + i * vb['vertex_size'] + at:base + i * vb['vertex_size'] + at + 4]] += 1
    return out


meshes = []
n_shadow = 0
for m in alr.meshes(b, h['roots'][0]):
    mat = m['materials'][m['material']]
    vb = m['vbufs'][m['vbuf']]
    if mat['shader'].startswith('sshadow'):
        meshes.append(alr_build.raw_mesh(b, m, h['resource_offset']))
        n_shadow += 1
        continue
    at = COLOUR_AT.get(vb['format'])
    pos, uv, _ = alr.read_vertices(b, h['resource_offset'], vb)
    fmt = alr.VERTEX_FORMATS[vb['format']]
    mtx = alr.node_matrix(m['nodes'], m['node'])
    rot = [[mtx[r][c] for c in range(3)] for r in range(3)]
    tris = alr.triangles_from_indices(m['indices'], m['primitive'])
    used = sorted({i for t in tris for i in t})
    remap = {o: n for n, o in enumerate(used)}
    verts = []
    for i in used:
        raw = struct.unpack_from('<I', b, h['resource_offset'] + vb['offset'] + i * vb['vertex_size'] + 12)[0]
        n = decode_normal(raw)
        n = tuple(sum(rot[r][k] * n[k] for k in range(3)) for r in range(3))
        col = None
        if at is not None:
            c = b[h['resource_offset'] + vb['offset'] + i * vb['vertex_size'] + at:][:4]
            col = (c[2], c[1], c[0], c[3])
        verts.append((alr.apply(mtx, pos[i]), n, uv[i] if uv else (0.0, 0.0), col))
    meshes.append(dict(verts=verts, tris=[tuple(remap[i] for i in t) for t in tris], texture_index=mat['textures'][0]))

nb, stats = alr_build.rebuild(b, replace={0: meshes})
print('rebuilt stage:', stats)
before, after = world_triangles(b, 0), world_triangles(nb, 0)
check(Counter(before) == Counter(after), 'stage from its own meshes: same %d triangles, UVs and textures' % len(before))
check(colours(b, 0) == colours(nb, 0), 'baked vertex colours carried over (%d distinct)' % len(colours(b, 0)))
shadow = lambda x: sorted(len(alr.triangles_from_indices(m['indices'], m['primitive'])) for m in alr.meshes(x, alr.header(x)['roots'][0])
                          if m['materials'][m['material']]['shader'].startswith('sshadow'))
check(shadow(b) == shadow(nb) and n_shadow > 0, 'shadow meshes carried over: %d meshes, triangles per mesh %s' % (n_shadow, shadow(nb)))
h2 = alr.header(nb)
check(h2['resource_offset'] % 0x1000 == 0 and h2['resource_offset'] + h2['resource_size'] == len(nb),
      'header: resource buffer aligned and sizes add up')
check(all(world_triangles(nb, r) == world_triangles(b, r) for r in (1, 2, 9)), 'other models unchanged')
check([t['name'] for t in alr.textures(nb)] == [t['name'] for t in alr.textures(b)], 'texture table unchanged')
if out_dir:
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, 'st04_rebuilt.alr'), 'wb').write(nb)

# 3. new texture
w = hgt = 4
levels = [bytes([0, 0, 255, 255]) * 16, bytes([0, 255, 0, 255]) * 4, bytes([255, 0, 0, 255])]
nb2, _ = alr_build.rebuild(b, textures=[dict(name='pd_test_tex1', width=w, height=hgt, levels=levels)])
t = alr.textures(nb2)[-1]
start = alr.header(nb2)['resource_offset'] + t['offset']
check((t['name'], t['width'], t['height'], t['mips'], t['raw_format']) == ('pd_test_tex1', 4, 4, 3, 0x86),
      'new texture entry reads back: %s' % ((t['name'], t['width'], t['height'], t['mips'], hex(t['raw_format'])),))
check(nb2[start:start + 64] == levels[0], 'new texture pixels stored at its offset')
print('RESULT: %d failure(s)' % len(fails))
