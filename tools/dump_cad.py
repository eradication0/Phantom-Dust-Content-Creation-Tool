"""Summarise com/stNN/comdata.cad (AI navigation mesh), optionally exporting it to OBJ.

  python tools/dump_cad.py <comdata.cad> [out.obj]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import cad

d = cad.read(open(sys.argv[1], 'rb').read())
ys = sorted(set(round(v[1]) for v in d['verts']))
print('%d verts, %d + %d quads, heights %s' % (len(d['verts']), len(d['quads_a']), len(d['quads_b']), ys))
if len(sys.argv) > 2:
    with open(sys.argv[2], 'w') as f:
        for v in d['verts']:
            f.write('v %f %f %f\n' % v)
        for name in ('quads_a', 'quads_b'):
            f.write('g %s\n' % name)
            for q in d[name]:
                f.write('f %d %d %d %d\n' % tuple(i + 1 for i in q))
    print('wrote', sys.argv[2])
