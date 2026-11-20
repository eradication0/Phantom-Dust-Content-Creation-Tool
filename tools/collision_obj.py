"""Export a stage's collision to OBJ (one group per chunk, named by surface type).

  python tools/collision_obj.py <stNN.dat> <out.obj>
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat

b = open(sys.argv[1], 'rb').read()
recs, vlists = dat.collision(b)
with open(sys.argv[2], 'w') as f:
    first, k = [], 1
    for vl in vlists:
        first.append(k)
        for v in vl.verts:
            f.write('v %f %f %f\n' % v)
            k += 1
    for i, r in enumerate(recs):
        if r.kind != dat.KIND_MESH:
            continue
        f.write('g chunk%04d_type%02x\n' % (i, r.type))
        o = first[r.vlist]
        for a, bb, c, _attr, _n in r.tris:
            f.write('f %d %d %d\n' % (a + o, bb + o, c + o))
print('wrote', sys.argv[2], dat.check_collision(b))
