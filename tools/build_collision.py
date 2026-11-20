"""Write new collision into a stage .dat (appended at the end; writes a NEW file).

  python tools/build_collision.py <in.dat> <out.dat> [--obj mesh.obj] [--keep] [--type 08] [--boxes-at-orbs]

  --obj FILE        triangles from an OBJ (y up, game units); polygons are fanned into triangles
  --keep            keep the map's existing collision triangles as well
  --type HEX        surface type for OBJ triangles (default 08, the common floor/wall type)
  --boxes-at-orbs   test: add a 40 x 40 x 25 invisible box at every spawn's first orb point
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat, collision_build as cb


def read_obj(path, st):
    vs, out = [], []
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == 'v':
            vs.append(tuple(float(x) for x in p[1:4]))
        elif p[0] == 'f':
            idx = [int(x.split('/')[0]) for x in p[1:]]
            idx = [i - 1 if i > 0 else len(vs) + i for i in idx]
            for k in range(1, len(idx) - 1):
                out.append((vs[idx[0]], vs[idx[k]], vs[idx[k + 1]], st))
    return out


def box(cx, y0, cz, w, h, st):
    """Closed box, outward-facing triangles."""
    x0, x1, z0, z1, y1 = cx - w / 2, cx + w / 2, cz - w / 2, cz + w / 2, y0 + h
    c = {(i, j, k): (x1 if i else x0, y1 if j else y0, z1 if k else z0) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
    quads = [((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),   # top    (+y)
             ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),   # bottom (-y)
             ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),   # +x
             ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),   # -x
             ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),   # +z
             ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))]   # -z
    tris = []
    for q in quads:
        a, b, cc, d = (c[k] for k in q)
        tris += [(a, b, cc, st), (a, cc, d, st)]
    return tris


ap = argparse.ArgumentParser()
ap.add_argument('src'); ap.add_argument('dst')
ap.add_argument('--obj'); ap.add_argument('--keep', action='store_true')
ap.add_argument('--type', default='08'); ap.add_argument('--boxes-at-orbs', action='store_true')
a = ap.parse_args()
if os.path.abspath(a.src) == os.path.abspath(a.dst):
    sys.exit('refusing to overwrite the input; write to a new file')
st = int(a.type, 16)
b = open(a.src, 'rb').read()
tris = []
if a.keep:
    tris += [(t[0], t[1], t[2], t[4]) for t in dat.triangles(b)]
if a.obj:
    tris += read_obj(a.obj, st)
if a.boxes_at_orbs:
    seen = set()
    for layout in dat.spawn_layouts(b):
        for s in layout:
            x, y, z = s.orbs[0]
            if (round(x), round(y), round(z)) not in seen:
                seen.add((round(x), round(y), round(z)))
                tris += box(x, y - 5, z, 40, 25, st)
    print('boxes:', len(seen))
if not tris:
    sys.exit('nothing to build: give --obj, --keep and/or --boxes-at-orbs')
block, stats = cb.build_block(tris)
out = cb.append_collision(b, block)
open(a.dst, 'wb').write(out)
print('built', stats, '->', a.dst, dat.check_collision(out))
