"""Summarise an .alr: header, record types per root, and optionally one root's node list.

  python tools/dump_alr.py <file.alr> [--root N]
"""
import argparse, collections, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import alr

ap = argparse.ArgumentParser()
ap.add_argument('file')
ap.add_argument('--root', type=int, help='print the node list of this root')
a = ap.parse_args()

b = open(a.file, 'rb').read()
h = alr.header(b)
print(a.file, len(b), 'bytes', {k: hex(v) for k, v in h.items() if k != 'roots'})
for i, r in enumerate(h['roots']):
    c = alr.chain(b, r)
    print('%3d %#8x size %#7x %s' % (i, r, sum(s for _, _, s in c), dict(sorted(collections.Counter(t for _, t, _ in c).items()))))
if a.root is not None:
    nodes, meshes = alr.skeleton(b, h['roots'][a.root])
    for i, n in enumerate(nodes):
        print('  %3d parent %-4s flags %04x meshes %d t(%.1f %.1f %.1f) r(%.2f %.2f %.2f) s(%.2f %.2f %.2f)' % (
            i, n['parent'], n['flags'], meshes.get(i, 0), *n['t'], *n['rot'], *n['scale']))
