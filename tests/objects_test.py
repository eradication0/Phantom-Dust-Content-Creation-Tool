"""Add test objects to an exported map and check them (plain Python, no Blender).

  python tests/objects_test.py <map.dat> <map.alr> <out_dir>

Takes a map exported by the add-on (e.g. the example map), removes every game original effect (clean slate)
and adds:
  crate  (2 m cube)        preset BREAK_SCATTER: intact + debris models, box collider, 3 placements
  bench  (slab on 2 legs)  preset CRUMBLE: intact + broken + debris models, collider, 2 placements
Writes out_dir/<name>.dat and .alr and prints what the game will read back.
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import alr, alr_build, dat, objects_build  # noqa: E402

dat_path, alr_path, out_dir = sys.argv[1:4]
os.makedirs(out_dir, exist_ok=True)
b_dat = open(dat_path, 'rb').read()
b_alr = open(alr_path, 'rb').read()
tex = {t['name']: t['index'] for t in alr.textures(b_alr)}
FLOOR = 64.0


def box(lo, hi, tex_index, light=(255, 255, 255, 255), uv_scale=1 / 20.0):
    """A box mesh for build_model: 6 faces with outward normals, planar UVs, flat lighting."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = lambda i: (x1 if i & 1 else x0, y1 if i & 2 else y0, z1 if i & 4 else z0)
    quads = [((0, 2, 3, 1), (0, 0, -1)), ((4, 5, 7, 6), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
             ((2, 6, 7, 3), (0, 1, 0)), ((0, 4, 6, 2), (-1, 0, 0)), ((1, 3, 7, 5), (1, 0, 0))]
    verts, tris = [], []
    for q, n in quads:
        base = len(verts)
        ax = [k for k in range(3) if n[k] == 0]
        shade = tuple(int(v * (0.65 if n[1] == -1 else 1.0)) for v in light[:3]) + (255,)
        for i in q:
            p = c(i)
            verts.append((p, n, (p[ax[0]] * uv_scale, p[ax[1]] * uv_scale), shade))
        tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    # winding: make each triangle's (b-a)x(c-a) point along its normal
    fixed = []
    for t in tris:
        A, B, C = (verts[i][0] for i in t)
        u = [B[k] - A[k] for k in range(3)]
        v = [C[k] - A[k] for k in range(3)]
        cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        n = verts[t[0]][1]
        fixed.append(t if sum(cr[k] * n[k] for k in range(3)) > 0 else (t[0], t[2], t[1]))
    return dict(verts=verts, tris=fixed, texture_index=tex_index)


def merge(*meshes):
    out = dict(verts=[], tris=[], texture_index=meshes[0]['texture_index'])
    for m in meshes:
        o = len(out['verts'])
        out['verts'] += m['verts']
        out['tris'] += [tuple(i + o for i in t) for t in m['tris']]
    return out


def collision(*boxes):
    tris = []
    for m in boxes:
        tris += [(m['verts'][a][0], m['verts'][b][0], m['verts'][c][0], 0x08) for a, b, c in m['tris']]
    return tris


metal, bricks = tex['ex_metal'], tex['ex_bricks']
# crate: 20 x 20 x 20 game units (2 m), origin at the bottom centre
crate = box((-10, 0, -10), (10, 20, 10), metal)
crate_debris = merge(*(box((x - 4, 0, z - 4), (x + 4, 7, z + 4), metal) for x, z in ((-6, -5), (5, -6), (-4, 6), (6, 5))))
# bench: 40 long, seat at 8..11 high, two legs
seat = box((-20, 8, -6), (20, 11, 6), bricks, light=(220, 220, 220, 255))
legs = [box((x - 2, 0, -5), (x + 2, 8, 5), bricks, light=(180, 180, 180, 255)) for x in (-16, 16)]
bench = merge(seat, *legs)
piece_l = merge(box((-20, 6, -6), (-1, 9, 6), bricks), legs[0])
piece_r = merge(box((1, 4, -6), (20, 7, 6), bricks), legs[1])
bench_debris = merge(box((-18, 0, -5), (-2, 3, 5), bricks), box((2, 0, -5), (18, 3, 5), bricks))

# Node layouts copied from the game's own object models (st04 box/desk/bench): see FORMATS.md
ROOT = dict(flags=0x0004)
models = [
    dict(meshes=[crate], nodes=[ROOT]),                                                   # crate intact
    dict(meshes=[dict(crate_debris, node=1)],                                             # crate debris
         nodes=[dict(flags=0x0004, values=(2, 2, 0, 0)), dict(flags=0x0004, parent=0)]),
    dict(meshes=[bench], nodes=[ROOT]),                                                   # bench intact
    dict(meshes=[dict(piece_l, node=1), dict(piece_r, node=2)],                           # bench broken: 2 pieces
         nodes=[dict(flags=0x0000), dict(flags=0x0004, parent=0, values=(3, 0, 0, 0)),
                dict(flags=0x0004, parent=0, values=(3, 0, 0, 0))]),
    dict(meshes=[bench_debris], nodes=[dict(flags=0x0004, values=(3, 3, 0, 0))]),         # bench debris
]
new_alr, st = alr_build.rebuild(b_alr, add_models=models)
r_crate, r_crate_d, r_bench, r_bench_b, r_bench_d = st['added_roots']

b2 = bytearray(b_dat)
n_fx = dat.clear_effects(b2)
cat_s, typ_s, _, _ = objects_build.PRESETS['BREAK_SCATTER']
cat_c, typ_c, _, _ = objects_build.PRESETS['CRUMBLE']
objects = [dict(name='pd_crate', roots=(r_crate, None, r_crate_d), collision=collision(crate)),
           dict(name='pd_bench', roots=(r_bench, r_bench_b, r_bench_d), collision=collision(seat, *legs))]
placements = [dict(object=0, category=cat_s, type=typ_s, pos=(x, FLOOR, z), rot=(0, r, 0))
              for x, z, r in ((-40, 30, 0.3), (-15, 45, 0.0), (35, -30, 1.0))]
placements += [dict(object=1, category=cat_c, type=typ_c, pos=(x, FLOOR, z), rot=(0, r, 0))
               for x, z, r in ((0, -130, 0.0), (-130, 0, math.pi / 2))]
new_dat = objects_build.add_objects(bytes(b2), objects, placements)

name = os.path.splitext(os.path.basename(dat_path))[0]
open(os.path.join(out_dir, name + '.dat'), 'wb').write(new_dat)
open(os.path.join(out_dir, name + '.alr'), 'wb').write(new_alr)

# read back as the game would
names, table, places = objects_build.read_objects(new_dat)
h = alr.header(new_alr)
print('effects removed:', n_fx, '| effects now:', len(dat.effects(new_dat)))
print('objects:', names)
for n, e in zip(names, table):
    recs, vls = dat.collision(new_dat, e[6])
    ntri = sum(len(r.tris) for r in recs if r.kind == 3)
    lo = [min(v[k] for vl in vls for v in vl.verts) for k in range(3)]
    hi = [max(v[k] for vl in vls for v in vl.verts) for k in range(3)]
    print('  %-9s models %s collision %d tris, local box %s..%s' % (n, [x if x != 0xFFFFFFFF else '-' for x in e[:3]], ntri,
          [round(x) for x in lo], [round(x) for x in hi]))
for p in places:
    print('  place %s cat %d type %d at (%.0f %.0f %.0f) rot %.2f' % (names[p['object']], p['category'], p['type'], *p['pos'], p['rot'][1]))
print('alr roots: %d (added %s); file sizes ok: %s' % (h['n_roots'], st['added_roots'],
      h['resource_offset'] + h['resource_size'] == len(new_alr) and struct.unpack_from('<I', new_dat, dat.H_FILE_SIZE)[0] == len(new_dat)))
for r in st['added_roots']:
    ms = alr.meshes(new_alr, h['roots'][r])
    print('  root %d: %d mesh(es), %d triangles, texture %s' % (r, len(ms), sum(len(alr.triangles_from_indices(m['indices'], m['primitive'])) for m in ms),
          {alr.textures(new_alr)[m['materials'][m['material']]['textures'][0]]['name'] for m in ms}))
print('main collision still fine:', dat.check_collision(new_dat))
